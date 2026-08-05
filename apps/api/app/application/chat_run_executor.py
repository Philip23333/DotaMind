"""Durable background execution of one Chat Run through the Agent Graph."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any
from uuid import UUID

from app.agentic.conversation.models import Turn
from app.agentic.graph import AgentGraphRunner
from app.agentic.runtime.streaming import (
    ResultStreamEvent,
    StatusStreamEvent,
    publish_stream_event,
)
from app.agentic.state import AgentRunState
from app.application.chat_run_repository import (
    ChatRunRepository,
    ChatRunRepositoryError,
    ChatRunSummary,
)
from app.application.postgres_chat_repository import PostgresChatRepository
from app.application.run_event_bus import RunEventBusError
from app.application.run_event_pump import bind_run_event_pump
from app.application.run_recovery import RunHeartbeat
from app.application.session_store import SessionStore
from app.observability import (
    record_chat_run,
    record_chat_run_cancellation,
)

TurnBuilder = Callable[[AgentRunState], Turn]
ResponseBuilder = Callable[[AgentRunState, UUID], dict[str, Any]]


@dataclass(frozen=True)
class ChatRunExecutionRequest:
    run_id: UUID
    browser_id: str
    session_id: UUID
    request_id: UUID
    query: str
    game: str


@dataclass(frozen=True)
class ChatRunExecutionResult:
    run: ChatRunSummary
    state: AgentRunState
    public_response: dict[str, Any]


class ChatRunExecutor:
    """Execute a pre-created Run while holding its session lease."""

    def __init__(
        self,
        *,
        runner: AgentGraphRunner,
        run_repository: ChatRunRepository,
        chat_repository: PostgresChatRepository,
        session_store: SessionStore,
        event_bus,
        worker_id: str,
        history_limit: int,
        build_turn: TurnBuilder,
        build_response: ResponseBuilder,
        heartbeat_interval_seconds: float = 0,
    ) -> None:
        self._runner = runner
        self._run_repository = run_repository
        self._chat_repository = chat_repository
        self._session_store = session_store
        self._event_bus = event_bus
        self._worker_id = worker_id
        self._history_limit = history_limit
        self._build_turn = build_turn
        self._build_response = build_response
        self._heartbeat_interval_seconds = heartbeat_interval_seconds

    async def execute(self, request: ChatRunExecutionRequest) -> ChatRunExecutionResult:
        """Run Graph, atomically commit its Turn, then publish terminal events."""

        started = monotonic()
        sid = str(request.session_id)
        try:
            async with self._session_store.transaction(sid):
                self._session_store.current_fencing_token(sid)
                fencing_token = await self._chat_repository.allocate_fencing_token(
                    request.browser_id,
                    request.session_id,
                )
                await self._run_repository.mark_running(
                    browser_id=request.browser_id,
                    run_id=request.run_id,
                    worker_id=self._worker_id,
                    fencing_token=fencing_token,
                )
                heartbeat = await self._start_heartbeat(request)
                try:
                    result = await self._execute_running(
                        request=request,
                        fencing_token=fencing_token,
                    )
                    record_chat_run(result.run.status, monotonic() - started)
                    return result
                finally:
                    if heartbeat is not None:
                        await heartbeat.stop()
        except asyncio.CancelledError:
            record_chat_run_cancellation("cancelled")
            record_chat_run("cancelled", monotonic() - started)
            raise
        except Exception:
            record_chat_run("failed", monotonic() - started)
            raise

    async def _execute_running(
        self,
        *,
        request: ChatRunExecutionRequest,
        fencing_token: int,
    ) -> ChatRunExecutionResult:
        history = await self._chat_repository.get_history(
            request.browser_id,
            request.session_id,
            limit=self._history_limit,
        )
        state = AgentRunState(
            query=request.query,
            game=request.game,
            history=history,
            session_memory_enabled=True,
            internal_session_id=request.session_id,
            internal_request_id=request.request_id,
            internal_run_id=request.run_id,
        )

        completed: ChatRunSummary | None = None
        async with bind_run_event_pump(
            bus=self._event_bus,
            run_id=request.run_id,
            session_id=request.session_id,
        ) as pump:
            try:
                publish_stream_event(StatusStreamEvent(status="running"))
                state = await self._runner.run(state)
                public_response = self._build_response(state, request.session_id)
                completed = await self._run_repository.complete_with_turn(
                    run_id=request.run_id,
                    worker_id=self._worker_id,
                    fencing_token=fencing_token,
                    public_response=public_response,
                    compact_turn=self._build_turn(state),
                )
                # PostgreSQL is committed before the terminal Redis events.
                publish_stream_event(ResultStreamEvent(response=public_response))
                publish_stream_event(StatusStreamEvent(status="completed"))
            except asyncio.CancelledError:
                terminal = await self._mark_cancelled_or_interrupted(request.run_id)
                record_chat_run_cancellation(terminal)
                publish_stream_event(
                    StatusStreamEvent(
                        status=terminal,
                        error_code="worker_cancelled" if terminal == "interrupted" else None,
                    )
                )
                raise
            except RunEventBusError:
                # A Redis/event failure must never turn an already committed
                # PostgreSQL Turn back into a failed Run.
                raise
            except Exception:
                await self._mark_failed(request.run_id)
                publish_stream_event(
                    StatusStreamEvent(status="failed", error_code="execution_error")
                )
                raise
            await pump.flush()

        assert completed is not None
        return ChatRunExecutionResult(
            run=completed,
            state=state,
            public_response=public_response,
        )

    async def _start_heartbeat(
        self, request: ChatRunExecutionRequest
    ) -> RunHeartbeat | None:
        if self._heartbeat_interval_seconds <= 0:
            return None
        execution_task = asyncio.current_task()

        async def cancel_execution() -> None:
            if execution_task is not None:
                execution_task.cancel()

        heartbeat = RunHeartbeat(
            repository=self._run_repository,
            run_id=request.run_id,
            worker_id=self._worker_id,
            interval_seconds=self._heartbeat_interval_seconds,
            on_cancel_requested=cancel_execution,
        )
        await heartbeat.start()
        return heartbeat

    async def _mark_failed(self, run_id: UUID) -> None:
        try:
            await self._run_repository.mark_failed(
                run_id=run_id,
                error_code="execution_error",
                worker_id=self._worker_id,
            )
        except Exception:
            return

    async def _mark_interrupted(self, run_id: UUID) -> None:
        try:
            await self._run_repository.mark_interrupted(
                run_id=run_id,
                error_code="worker_cancelled",
                worker_id=self._worker_id,
            )
        except Exception:
            return

    async def _mark_cancelled_or_interrupted(
        self, run_id: UUID
    ) -> str:
        try:
            await self._run_repository.mark_cancelled(
                run_id=run_id,
                worker_id=self._worker_id,
            )
            return "cancelled"
        except ChatRunRepositoryError:
            await self._mark_interrupted(run_id)
            return "interrupted"


__all__ = [
    "ChatRunExecutionRequest",
    "ChatRunExecutionResult",
    "ChatRunExecutor",
]
