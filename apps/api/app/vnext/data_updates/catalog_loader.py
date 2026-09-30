"""Background validation and in-memory switching for catalog snapshots."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from typing import TypeVar

from app.vnext.data_updates.catalog_store import (
    CatalogSnapshot,
    CatalogSnapshotStore,
    CatalogStoreError,
)

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


async def _await_task_without_abandoning(task: asyncio.Task[_T]) -> _T:
    """Wait for a task to finish, then re-raise any cancellation received."""

    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if cancellation is None:
                cancellation = exc
            if not task.done():
                continue
            try:
                result = task.result()
            except BaseException:
                # Retrieving task.result() consumes any worker exception.
                raise cancellation from None
            break
        except BaseException:
            if cancellation is not None:
                raise cancellation from None
            raise
        else:
            break

    if cancellation is not None:
        raise cancellation
    return result


async def _call_in_thread(function: Callable[[], _T]) -> _T:
    task = asyncio.create_task(asyncio.to_thread(function))
    return await _await_task_without_abandoning(task)


class CatalogNotInitializedError(RuntimeError):
    """Raised when no successfully loaded catalog snapshot is available."""

    reason = "not_initialized"

    def __init__(self) -> None:
        super().__init__("catalog snapshot is not initialized")


class CatalogSnapshotLoader:
    """Keep one validated snapshot available while checking for publications."""

    def __init__(
        self,
        store: CatalogSnapshotStore,
        *,
        poll_interval_seconds: float = 30.0,
    ) -> None:
        if isinstance(poll_interval_seconds, bool) or not isinstance(
            poll_interval_seconds, (int, float)
        ):
            raise ValueError("poll_interval_seconds must be finite and positive")
        try:
            interval = float(poll_interval_seconds)
        except OverflowError as exc:
            raise ValueError("poll_interval_seconds must be finite and positive") from exc
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("poll_interval_seconds must be finite and positive")

        self._store = store
        self._poll_interval_seconds = interval
        self._snapshot: CatalogSnapshot | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._refresh_lock = asyncio.Lock()

    async def start(self) -> None:
        """Load the current snapshot before starting one background poller."""

        task = self._poll_task
        if task is not None and not task.done():
            return

        self._stop_event.clear()
        snapshot = await _call_in_thread(self._store.load_current)
        if snapshot is None:
            raise CatalogNotInitializedError()

        self._snapshot = snapshot
        self._poll_task = asyncio.create_task(
            self._poll(), name="catalog-snapshot-poller"
        )

    async def stop(self) -> None:
        """Stop polling and wait for any active refresh to finish."""

        self._stop_event.set()
        task = self._poll_task
        cancellation: asyncio.CancelledError | None = None
        failure: BaseException | None = None
        try:
            if task is not None:
                await _await_task_without_abandoning(task)
        except asyncio.CancelledError as exc:
            cancellation = exc
        except BaseException as exc:
            failure = exc

        barrier = asyncio.create_task(self._wait_for_refresh_idle())
        try:
            await _await_task_without_abandoning(barrier)
        except asyncio.CancelledError as exc:
            if cancellation is None:
                cancellation = exc
        except BaseException as exc:
            if failure is None:
                failure = exc
        finally:
            if self._poll_task is task:
                self._poll_task = None

        if cancellation is not None:
            raise cancellation from None
        if failure is not None:
            raise failure

    async def refresh_once(self) -> bool:
        """Check the current revision and atomically adopt a valid new snapshot."""

        async with self._refresh_lock:
            current = self._snapshot
            if current is None:
                raise CatalogNotInitializedError()

            revision = await _call_in_thread(self._store.read_current_revision)
            if revision == current.revision:
                return False

            candidate = await _call_in_thread(self._store.load_current)
            if candidate is None:
                raise CatalogNotInitializedError()
            if candidate.revision == current.revision:
                return False

            self._snapshot = candidate
            return True

    async def _wait_for_refresh_idle(self) -> None:
        async with self._refresh_lock:
            pass

    def current(self) -> CatalogSnapshot:
        """Return the current snapshot reference without doing I/O."""

        snapshot = self._snapshot
        if snapshot is None:
            raise CatalogNotInitializedError()
        return snapshot

    async def _poll(self) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._poll_interval_seconds
                )
            except TimeoutError:
                try:
                    await self.refresh_once()
                except CatalogStoreError as exc:
                    logger.warning("catalog snapshot refresh failed: %s", exc.reason)
                except CatalogNotInitializedError:
                    logger.warning(
                        "catalog snapshot refresh failed: %s",
                        CatalogNotInitializedError.reason,
                    )
                continue
            return
