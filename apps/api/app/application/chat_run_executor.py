"""Durable background execution of one Chat Run through the Agent Graph."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any
from uuid import UUID

from app.agentic.conversation.models import DialogueTurn
from app.agentic.graph import AgentGraphRunner
from app.agentic.runtime.checkpoint import CheckpointSnapshot
from app.agentic.runtime.checkpoint_adapters import apply_match_selection
from app.agentic.runtime.models import RunContext
from app.agentic.runtime.streaming import (
    CheckpointStreamEvent,
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
from app.application.conversation_memory import ConversationMemoryService
from app.application.history_lookup import HistoryLookupContext, bind_history_lookup_context
from app.application.plan_service import TurnBuildResult
from app.application.postgres_chat_repository import PostgresChatRepository
from app.application.run_event_bus import RunEventBusError
from app.application.run_event_pump import bind_run_event_pump
from app.application.run_recovery import RunHeartbeat
from app.application.session_store import SessionStore, SessionStoreError
from app.observability import (
    record_chat_run,
    record_chat_run_cancellation,
)

TurnBuilder = Callable[[AgentRunState], Awaitable[TurnBuildResult]]
ResponseBuilder = Callable[[AgentRunState, UUID], dict[str, Any]]


@dataclass(frozen=True)
class ChatRunExecutionRequest:
    run_id: UUID
    browser_id: str
    session_id: UUID
    request_id: UUID
    query: str
    game: str
    resume: bool = False


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
        memory_service: ConversationMemoryService,
        event_bus,
        worker_id: str,
        history_lookup_max_turns: int = 8,
        history_lookup_max_chars: int = 12_000,
        build_turn: TurnBuilder,
        build_response: ResponseBuilder,
        heartbeat_interval_seconds: float = 0,
    ) -> None:
        self._runner = runner
        self._run_repository = run_repository
        self._chat_repository = chat_repository
        self._session_store = session_store
        self._memory_service = memory_service
        self._event_bus = event_bus
        self._worker_id = worker_id
        self._history_lookup_max_turns = history_lookup_max_turns
        self._history_lookup_max_chars = history_lookup_max_chars
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
                running = await self._run_repository.mark_running(
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
                        running=running,
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
        running: ChatRunSummary,
    ) -> ChatRunExecutionResult:
        recent_messages, next_turn_index = await self._memory_service.load_recent_messages(
            request.browser_id,
            request.session_id,
        )
        state = (
            self._state_from_checkpoint(
                request=request,
                running=running,
                recent_messages=recent_messages,
                next_turn_index=next_turn_index,
            )
            if request.resume
            else AgentRunState(
                query=request.query,
                game=request.game,
                recent_messages=recent_messages,
                next_turn_index=next_turn_index,
                internal_session_id=request.session_id,
                internal_request_id=request.request_id,
                internal_run_id=request.run_id,
            )
        )

        completed: ChatRunSummary | None = None
        committed = False
        paused_persisted = False
        async with bind_run_event_pump(
            bus=self._event_bus,
            run_id=request.run_id,
            session_id=request.session_id,
        ) as pump:
            try:
                publish_stream_event(StatusStreamEvent(status="running"))
                with bind_history_lookup_context(
                    HistoryLookupContext(
                        chat_repository=self._chat_repository,
                        browser_id=request.browser_id,
                        session_id=request.session_id,
                        max_turns=self._history_lookup_max_turns,
                        max_chars=self._history_lookup_max_chars,
                    )
                ):
                    state = await self._runner.run(state)
                if state.status == "waiting_input":
                    if state.checkpoint is None:
                        raise ChatRunRepositoryError("checkpoint_missing")
                    snapshot = self._checkpoint_snapshot(state)
                    paused = await self._run_repository.mark_waiting_input(
                        run_id=request.run_id,
                        worker_id=self._worker_id,
                        fencing_token=fencing_token,
                        checkpoint_state=snapshot.model_dump(mode="json"),
                    )
                    paused_persisted = True
                    publish_stream_event(
                        CheckpointStreamEvent(
                            checkpoint=state.checkpoint.model_dump(mode="json")
                        )
                    )
                    publish_stream_event(StatusStreamEvent(status="waiting_input"))
                    await pump.flush()
                    return ChatRunExecutionResult(
                        run=paused,
                        state=state,
                        public_response={},
                    )
                public_response = self._build_response(state, request.session_id)
                turn_result = await self._build_turn(state)
                completed = await self._run_repository.complete_with_turn(
                    run_id=request.run_id,
                    worker_id=self._worker_id,
                    fencing_token=fencing_token,
                    public_response=public_response,
                    assistant_message=turn_result.assistant_message,
                    compact_turn=turn_result.turn,
                    expected_next_turn_index=state.next_turn_index,
                )
                committed = True
                try:
                    await self._memory_service.record_committed_turn(
                        request.browser_id,
                        request.session_id,
                        DialogueTurn(
                            turn_index=state.next_turn_index,
                            user_message=request.query,
                            assistant_message=turn_result.assistant_message,
                        ),
                    )
                except SessionStoreError:
                    # PostgreSQL is authoritative; a cache failure must not turn a
                    # committed Run into a failed Run.
                    pass
                # PostgreSQL is committed before the terminal Redis events.
                publish_stream_event(ResultStreamEvent(response=public_response))
                publish_stream_event(StatusStreamEvent(status="completed"))
            except asyncio.CancelledError:
                if committed:
                    raise
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
                # Before the durable commit, the Run still needs a terminal
                # failure state. After the commit, PostgreSQL remains completed
                # even if terminal Redis/event delivery fails.
                if not committed and not paused_persisted:
                    await self._mark_failed(request.run_id)
                raise
            except Exception:
                if committed or paused_persisted:
                    raise
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

    def _state_from_checkpoint(
        self,
        *,
        request: ChatRunExecutionRequest,
        running: ChatRunSummary,
        recent_messages: list,
        next_turn_index: int,
    ) -> AgentRunState:
        if running.checkpoint_state is None:
            raise ChatRunRepositoryError("checkpoint_missing")
        snapshot = CheckpointSnapshot.model_validate(running.checkpoint_state)
        try:
            plan = apply_match_selection(
                snapshot.plan,
                snapshot.checkpoint,
                snapshot.selected_option_id,
            )
        except ValueError as exc:
            raise ChatRunRepositoryError(str(exc)) from exc
        source_tool_call_id = snapshot.checkpoint.source_tool_call_id
        # Snapshot records remain durable audit data, but a resumed execution
        # state starts with fresh result/dispatch collections. The tools node
        # traverses the plan again: preceding calls reuse the fingerprint cache
        # and emit one fresh cache-reuse record, while the selected ambiguous
        # call reruns with its patched arguments.
        executed_call_fingerprints = {
            fingerprint: cached
            for fingerprint, cached in snapshot.executed_call_fingerprints.items()
            if cached.call_id != source_tool_call_id
        }
        started_at = running.started_at or datetime.now(UTC)
        run_context = RunContext(
            run_id=request.run_id,
            request_id=request.request_id,
            session_id=request.session_id,
            started_at=started_at,
            deadline_at=started_at
            + timedelta(seconds=self._runner.runtime_policy.max_elapsed_seconds),
        )
        return AgentRunState(
            query=request.query,
            game=request.game,
            recent_messages=recent_messages,
            next_turn_index=next_turn_index,
            internal_session_id=request.session_id,
            internal_request_id=request.request_id,
            internal_run_id=request.run_id,
            run_context=run_context,
            run_budget=snapshot.run_budget,
            run_started_monotonic=self._runner.clock.monotonic(),
            attempt_index=snapshot.attempt_index,
            attempt_started_at=started_at,
            attempt_started_monotonic=self._runner.clock.monotonic(),
            attempts=snapshot.attempts,
            executed_call_fingerprints=executed_call_fingerprints,
            plan=plan,
            planner_required_evidence=snapshot.planner_required_evidence,
            global_required_evidence=snapshot.global_required_evidence,
            effective_required_evidence=snapshot.effective_required_evidence,
            required_evidence_sources=snapshot.required_evidence_sources,
            mandatory_evidence_by_call=snapshot.mandatory_evidence_by_call,
            tool_results=[],
            tool_dispatch_records=[],
            decision_kind="tool_plan",
            resume_node=snapshot.checkpoint.resume_node,
            status="ok",
        )

    @staticmethod
    def _checkpoint_snapshot(state: AgentRunState) -> CheckpointSnapshot:
        if state.checkpoint is None or state.plan is None or state.run_budget is None:
            raise ChatRunRepositoryError("checkpoint_snapshot_incomplete")
        return CheckpointSnapshot(
            checkpoint=state.checkpoint,
            plan=state.plan,
            tool_results=state.tool_results,
            tool_dispatch_records=state.tool_dispatch_records,
            run_budget=state.run_budget,
            attempt_index=state.attempt_index,
            attempts=state.attempts,
            executed_call_fingerprints=state.executed_call_fingerprints,
            planner_required_evidence=state.planner_required_evidence,
            global_required_evidence=state.global_required_evidence,
            effective_required_evidence=state.effective_required_evidence,
            required_evidence_sources=state.required_evidence_sources,
            mandatory_evidence_by_call=state.mandatory_evidence_by_call,
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
