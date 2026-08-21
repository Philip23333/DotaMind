"""Application service that creates durable Runs and dispatches them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from app.application.background_run_manager import BackgroundRunManager
from app.application.chat_run_executor import (
    ChatRunExecutionRequest,
    ChatRunExecutor,
)
from app.application.chat_run_repository import (
    ChatRunCancelResult,
    ChatRunCreateResult,
    ChatRunRepository,
    ChatRunRepositoryError,
    ChatRunResumeResult,
)
from app.application.idempotency import build_request_hash
from app.observability import record_chat_run_cancellation


@dataclass(frozen=True)
class ChatRunCreateOutcome:
    action: Literal["created", "replayed"]
    run: object


class ChatRunRuntime:
    """Create queued Runs and detach execution from the HTTP request."""

    def __init__(
        self,
        *,
        repository: ChatRunRepository,
        manager: BackgroundRunManager,
        executor: ChatRunExecutor,
        event_bus=None,
    ) -> None:
        self._repository = repository
        self._manager = manager
        self._executor = executor
        self._event_bus = event_bus

    async def create_run(
        self,
        *,
        browser_id: str,
        session_id: UUID,
        request_id: UUID,
        query: str,
        game: str,
    ) -> ChatRunCreateResult:
        run_id = uuid4()
        result = await self._repository.create_or_get_run(
            browser_id=browser_id,
            session_id=session_id,
            request_id=request_id,
            payload_hash=build_request_hash(query=query, game=game),
            user_query=query,
            run_id=run_id,
        )
        if result.action == "replayed":
            return result

        execution_request = ChatRunExecutionRequest(
            run_id=run_id,
            browser_id=browser_id,
            session_id=session_id,
            request_id=request_id,
            query=query,
            game=game,
        )
        try:
            await self._manager.submit(
                run_id,
                lambda: self._executor.execute(execution_request),
            )
        except Exception as exc:
            # A newly queued Run must not become an unobservable permanent
            # queued row if this worker cannot accept its task.
            await self._repository.mark_failed(
                run_id=run_id,
                error_code="dispatch_failed",
            )
            raise ChatRunRepositoryError("dispatch_failed") from exc
        return result

    async def cancel_run(self, *, browser_id: str, run_id: UUID) -> ChatRunCancelResult:
        result = await self._repository.request_cancel(
            browser_id=browser_id,
            run_id=run_id,
        )
        record_chat_run_cancellation(result.action)
        await self._manager.cancel(run_id)
        if self._event_bus is not None:
            try:
                await self._event_bus.publish_cancel(
                    run_id=run_id,
                    target_worker_id=result.run.worker_id,
                )
            except Exception:
                # PostgreSQL cancel_requested is authoritative; heartbeat will
                # observe it even when the notification path is unavailable.
                pass
        return result

    async def resume_run(
        self,
        *,
        browser_id: str,
        run_id: UUID,
        checkpoint_type: str,
        option_id: str,
    ) -> ChatRunResumeResult:
        result = await self._repository.resume_checkpoint(
            browser_id=browser_id,
            run_id=run_id,
            checkpoint_type=checkpoint_type,
            option_id=option_id,
        )
        run = result.run
        execution_request = ChatRunExecutionRequest(
            run_id=run.run_id,
            browser_id=browser_id,
            session_id=run.session_id,
            request_id=run.request_id,
            query=run.user_query,
            game="dota2",
            resume=True,
        )
        try:
            await self._manager.submit(
                run.run_id,
                lambda: self._executor.execute(execution_request),
            )
        except Exception as exc:
            await self._repository.mark_failed(
                run_id=run.run_id,
                error_code="dispatch_failed",
            )
            raise ChatRunRepositoryError("dispatch_failed") from exc
        return result


__all__ = ["ChatRunCreateOutcome", "ChatRunRuntime"]
