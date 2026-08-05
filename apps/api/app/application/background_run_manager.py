"""Per-worker lifecycle management for detached chat Run tasks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID, uuid4

from app.application.run_event_bus import RunCancelNotification

RunCallable = Callable[[], Awaitable[None]]
ShutdownCallback = Callable[[UUID], Awaitable[None]]
CancelSubscriber = Callable[[], AsyncIterator[RunCancelNotification]]


class BackgroundRunManagerError(RuntimeError):
    """Base error for worker-local Run task management."""


class RunAlreadyManagedError(BackgroundRunManagerError):
    """Raised when a worker already owns an active task for a Run."""


class RunManagerClosedError(BackgroundRunManagerError):
    """Raised when a new Run is submitted after worker shutdown begins."""


class BackgroundRunManager:
    """Run detached executions with a per-API-worker concurrency cap.

    The manager owns asyncio tasks only. PostgreSQL remains the source of truth
    for Run state; callers provide the state transitions through the submitted
    coroutine and the optional shutdown callback.
    """

    def __init__(
        self,
        *,
        max_concurrent_runs: int,
        worker_id: str | None = None,
        on_shutdown: ShutdownCallback | None = None,
        cancel_subscriber: CancelSubscriber | None = None,
    ) -> None:
        if max_concurrent_runs < 1:
            raise ValueError("max_concurrent_runs must be at least 1")
        self.worker_id = worker_id or str(uuid4())
        self.max_concurrent_runs = max_concurrent_runs
        self._semaphore = asyncio.Semaphore(max_concurrent_runs)
        self._on_shutdown = on_shutdown
        self._cancel_subscriber = cancel_subscriber
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._failures: dict[UUID, BaseException] = {}
        self._listener_failure: BaseException | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._accepting = True
        self._logger = logging.getLogger(__name__)

    @property
    def accepting(self) -> bool:
        return self._accepting

    @property
    def active_run_ids(self) -> frozenset[UUID]:
        return frozenset(self._tasks)

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    @property
    def failures(self) -> dict[UUID, BaseException]:
        return dict(self._failures)

    @property
    def listener_failure(self) -> BaseException | None:
        return self._listener_failure

    async def start(self) -> None:
        """Start the optional Redis cancellation listener for this worker."""

        if self._cancel_subscriber is None or self._listener_task is not None:
            return
        self._listener_task = asyncio.create_task(
            self._listen_for_cancellations(),
            name=f"run-cancel-listener:{self.worker_id}",
        )

    async def submit(self, run_id: UUID, runner: RunCallable) -> asyncio.Task[None]:
        """Schedule one Run and return its task for optional observation."""

        async with self._lock:
            if not self._accepting:
                raise RunManagerClosedError("run manager is shutting down")
            existing = self._tasks.get(run_id)
            if existing is not None and not existing.done():
                raise RunAlreadyManagedError(f"run {run_id} is already managed")
            task = asyncio.create_task(
                self._run(run_id, runner),
                name=f"background-run:{run_id}",
            )
            self._tasks[run_id] = task
            task.add_done_callback(self._task_done)
            return task

    async def cancel(self, run_id: UUID) -> bool:
        """Cancel a worker-local task without changing durable Run state."""

        async with self._lock:
            task = self._tasks.get(run_id)
            if task is None or task.done():
                return False
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return True

    async def shutdown(self) -> None:
        """Stop accepting Runs and cancel all in-flight worker tasks."""

        async with self._lock:
            self._accepting = False
            tasks = [(run_id, task) for run_id, task in self._tasks.items() if not task.done()]
            for _, task in tasks:
                task.cancel()

            listener = self._listener_task
            if listener is not None:
                listener.cancel()

        await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
        if listener is not None:
            await asyncio.gather(listener, return_exceptions=True)
            self._listener_task = None
        if self._on_shutdown is not None:
            await asyncio.gather(
                *(self._on_shutdown(run_id) for run_id, _ in tasks),
                return_exceptions=False,
            )

    async def _run(self, run_id: UUID, runner: RunCallable) -> None:
        async with self._semaphore:
            await runner()

    def _task_done(self, task: asyncio.Task[None]) -> None:
        run_id = next(
            (candidate for candidate, current in self._tasks.items() if current is task),
            None,
        )
        if run_id is None:
            return
        self._tasks.pop(run_id, None)
        if task.cancelled():
            return
        failure = task.exception()
        if failure is not None:
            self._failures[run_id] = failure
            self._logger.error(
                "background Run failed",
                extra={"run_id": str(run_id)},
                exc_info=(type(failure), failure, failure.__traceback__),
            )

    async def _listen_for_cancellations(self) -> None:
        assert self._cancel_subscriber is not None
        try:
            async for notification in self._cancel_subscriber():
                if (
                    notification.target_worker_id is not None
                    and notification.target_worker_id != self.worker_id
                ):
                    continue
                await self.cancel(notification.run_id)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._listener_failure = exc
            self._logger.error(
                "background Run cancellation listener failed",
                extra={"worker_id": self.worker_id},
                exc_info=(type(exc), exc, exc.__traceback__),
            )


__all__ = [
    "BackgroundRunManager",
    "BackgroundRunManagerError",
    "RunAlreadyManagedError",
    "RunManagerClosedError",
]
