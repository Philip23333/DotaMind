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
    ChatRunCreateResult,
    ChatRunRepository,
    ChatRunRepositoryError,
)
from app.application.idempotency import build_request_hash


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
    ) -> None:
        self._repository = repository
        self._manager = manager
        self._executor = executor

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


__all__ = ["ChatRunCreateOutcome", "ChatRunRuntime"]
