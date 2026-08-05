"""Heartbeat and stale-Run recovery loops for background workers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.chat_run_repository import (
    ChatRunRepository,
    ChatRunRepositoryError,
    ChatRunTerminalError,
)
from app.observability import record_stale_chat_runs

CancelCallback = Callable[[], Awaitable[None]]


class RunHeartbeat:
    """Refresh one active Run and cancel its executor when cancellation is durable."""

    def __init__(
        self,
        *,
        repository: ChatRunRepository,
        run_id: UUID,
        worker_id: str,
        interval_seconds: float,
        on_cancel_requested: CancelCallback,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("heartbeat interval must be positive")
        self._repository = repository
        self._run_id = run_id
        self._worker_id = worker_id
        self._interval_seconds = interval_seconds
        self._on_cancel_requested = on_cancel_requested
        self._task: asyncio.Task[None] | None = None
        self.failure: BaseException | None = None

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("heartbeat already started")
        self._task = asyncio.create_task(
            self._run(),
            name=f"run-heartbeat:{self._run_id}",
        )

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self._task = None

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval_seconds)
                summary = await self._repository.update_heartbeat(
                    run_id=self._run_id,
                    worker_id=self._worker_id,
                )
                if summary.status == "cancel_requested":
                    await self._on_cancel_requested()
                    return
        except asyncio.CancelledError:
            raise
        except ChatRunTerminalError:
            return
        except ChatRunRepositoryError as exc:
            self.failure = exc


class RunStaleSweeper:
    """Conditionally interrupt queued/running Runs whose heartbeat expired."""

    def __init__(
        self,
        *,
        repository: ChatRunRepository,
        stale_after_seconds: float,
        interval_seconds: float,
        error_code: str = "stale_worker",
    ) -> None:
        if stale_after_seconds <= 0 or interval_seconds <= 0:
            raise ValueError("stale and sweep intervals must be positive")
        self._repository = repository
        self._stale_after = stale_after_seconds
        self._interval_seconds = interval_seconds
        self._error_code = error_code
        self._task: asyncio.Task[None] | None = None
        self.failure: BaseException | None = None

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("stale sweeper already started")
        self._task = asyncio.create_task(self._run(), name="chat-run-stale-sweeper")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self._task = None

    async def run_once(self, *, now: datetime | None = None) -> list[UUID]:
        reference = now or datetime.now(UTC)
        stale_before = reference - timedelta(seconds=self._stale_after)
        run_ids = await self._repository.interrupt_stale_runs(
            stale_before=stale_before,
            error_code=self._error_code,
        )
        record_stale_chat_runs(len(run_ids))
        return run_ids

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval_seconds)
                await self.run_once()
        except asyncio.CancelledError:
            raise
        except ChatRunRepositoryError as exc:
            self.failure = exc


__all__ = ["RunHeartbeat", "RunStaleSweeper"]
