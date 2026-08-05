from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.application.background_run_manager import (
    BackgroundRunManager,
    RunAlreadyManagedError,
    RunManagerClosedError,
)


def test_manager_enforces_per_worker_concurrency_and_preserves_distinct_runs() -> None:
    async def scenario() -> None:
        manager = BackgroundRunManager(max_concurrent_runs=2, worker_id="worker-a")
        started: list[str] = []
        release = asyncio.Event()

        async def runner(name: str) -> None:
            started.append(name)
            await release.wait()

        first = await manager.submit(uuid4(), lambda: runner("first"))
        second = await manager.submit(uuid4(), lambda: runner("second"))
        third = await manager.submit(uuid4(), lambda: runner("third"))
        await asyncio.sleep(0)

        assert sorted(started) == ["first", "second"]
        assert manager.active_count == 3
        release.set()
        await asyncio.gather(first, second, third)
        assert sorted(started) == ["first", "second", "third"]
        assert manager.active_count == 0

    asyncio.run(scenario())


def test_manager_cancels_only_target_and_marks_shutdown_runs() -> None:
    async def scenario() -> None:
        shutdown_ids: list = []
        manager = BackgroundRunManager(
            max_concurrent_runs=2,
            on_shutdown=lambda run_id: _record_shutdown(shutdown_ids, run_id),
        )
        target_id = uuid4()
        other_id = uuid4()
        target_started = asyncio.Event()
        other_started = asyncio.Event()
        release_other = asyncio.Event()

        async def target() -> None:
            target_started.set()
            await asyncio.Event().wait()

        async def other() -> None:
            other_started.set()
            await release_other.wait()

        target_task = await manager.submit(target_id, target)
        other_task = await manager.submit(other_id, other)
        await asyncio.gather(target_started.wait(), other_started.wait())
        assert await manager.cancel(target_id) is True
        assert target_task.cancelled()
        assert other_id in manager.active_run_ids

        await manager.shutdown()
        release_other.set()
        await asyncio.gather(other_task, return_exceptions=True)
        assert shutdown_ids == [other_id]
        assert manager.accepting is False
        with pytest.raises(RunManagerClosedError):
            await manager.submit(uuid4(), lambda: asyncio.sleep(0))

    asyncio.run(scenario())


def test_manager_rejects_duplicate_active_run() -> None:
    async def scenario() -> None:
        manager = BackgroundRunManager(max_concurrent_runs=1)
        run_id = uuid4()
        release = asyncio.Event()
        task = await manager.submit(run_id, release.wait)
        with pytest.raises(RunAlreadyManagedError):
            await manager.submit(run_id, release.wait)
        await manager.cancel(run_id)
        assert task.cancelled()

    asyncio.run(scenario())


async def _record_shutdown(target: list, run_id) -> None:
    target.append(run_id)
