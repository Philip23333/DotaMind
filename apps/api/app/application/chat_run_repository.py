"""Contracts and persistence DTOs for durable background chat Runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from app.agentic.conversation.models import Turn

ChatRunStatus = Literal[
    "queued",
    "running",
    "cancel_requested",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
]
ACTIVE_RUN_STATUSES: frozenset[ChatRunStatus] = frozenset(
    {"queued", "running", "cancel_requested"}
)
TERMINAL_RUN_STATUSES: frozenset[ChatRunStatus] = frozenset(
    {"completed", "failed", "cancelled", "interrupted"}
)


class ChatRunRepositoryError(RuntimeError):
    """Infrastructure or stable domain failure in the Run repository."""

    def __init__(self, code: str = "unavailable") -> None:
        super().__init__(code)
        self.code = code


class ChatRunNotFoundError(ChatRunRepositoryError):
    def __init__(self) -> None:
        super().__init__("not_found")


class ChatRunIdempotencyConflictError(ChatRunRepositoryError):
    def __init__(self) -> None:
        super().__init__("idempotency_conflict")


class ChatRunActiveError(ChatRunRepositoryError):
    def __init__(self) -> None:
        super().__init__("chat_run_active")


class ChatRunFencingLostError(ChatRunRepositoryError):
    def __init__(self) -> None:
        super().__init__("fencing_lost")


class ChatRunStateError(ChatRunRepositoryError):
    def __init__(self, code: str = "invalid_state") -> None:
        super().__init__(code)


class ChatRunTerminalError(ChatRunRepositoryError):
    def __init__(self) -> None:
        super().__init__("run_terminal")


@dataclass(frozen=True)
class ChatRunSummary:
    run_id: UUID
    session_id: UUID
    request_id: UUID
    payload_hash: str
    user_query: str
    status: ChatRunStatus
    fencing_token: int | None
    worker_id: str | None
    last_event_sequence: int
    result_turn_id: UUID | None
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    heartbeat_at: datetime | None
    cancel_requested_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True)
class ChatRunCreateResult:
    action: Literal["created", "replayed"]
    run: ChatRunSummary


@dataclass(frozen=True)
class ChatRunCancelResult:
    action: Literal["requested", "already_requested"]
    run: ChatRunSummary


class ChatRunRepository(Protocol):
    async def create_or_get_run(
        self,
        *,
        browser_id: str,
        session_id: UUID,
        request_id: UUID,
        payload_hash: str,
        user_query: str,
        run_id: UUID,
    ) -> ChatRunCreateResult: ...

    async def get_run_for_browser(self, browser_id: str, run_id: UUID) -> ChatRunSummary: ...

    async def get_active_run(
        self, browser_id: str, session_id: UUID
    ) -> ChatRunSummary | None: ...

    async def mark_running(
        self, *, browser_id: str, run_id: UUID, worker_id: str, fencing_token: int
    ) -> ChatRunSummary: ...

    async def update_heartbeat(self, *, run_id: UUID, worker_id: str) -> ChatRunSummary: ...

    async def request_cancel(
        self, *, browser_id: str, run_id: UUID
    ) -> ChatRunCancelResult: ...

    async def mark_cancelled(
        self, *, run_id: UUID, worker_id: str | None = None
    ) -> ChatRunSummary: ...

    async def mark_failed(
        self, *, run_id: UUID, error_code: str, worker_id: str | None = None
    ) -> ChatRunSummary: ...

    async def mark_interrupted(
        self, *, run_id: UUID, error_code: str, worker_id: str | None = None
    ) -> ChatRunSummary: ...

    async def interrupt_stale_runs(
        self, *, stale_before: datetime, error_code: str
    ) -> list[UUID]: ...

    async def complete_with_turn(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        fencing_token: int,
        public_response: dict[str, Any],
        assistant_message: str,
        compact_turn: Turn,
        expected_next_turn_index: int | None = None,
    ) -> ChatRunSummary: ...
