"""Contracts for durable, replayable events belonging to one chat Run."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.agentic.runtime.streaming import PlanStreamEvent


class RunEventBusError(RuntimeError):
    """Stable event-bus failure exposed to the Run observer."""

    def __init__(self, code: str = "unavailable") -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class StoredRunEvent:
    run_id: UUID
    session_id: UUID
    sequence: int
    event: PlanStreamEvent


@dataclass(frozen=True)
class RunCancelNotification:
    run_id: UUID
    target_worker_id: str | None


class RunEventBus(Protocol):
    async def append(
        self, *, run_id: UUID, session_id: UUID, event: PlanStreamEvent
    ) -> StoredRunEvent: ...

    async def read_after(
        self, *, run_id: UUID, session_id: UUID, after: int
    ) -> list[StoredRunEvent]: ...

    async def wait_after(
        self, *, run_id: UUID, session_id: UUID, after: int, timeout_seconds: int
    ) -> list[StoredRunEvent]: ...

    async def publish_cancel(
        self, *, run_id: UUID, target_worker_id: str | None
    ) -> None: ...

    def subscribe_cancellations(self) -> AsyncIterator[RunCancelNotification]: ...

    async def ping(self) -> None: ...

    async def aclose(self) -> None: ...
