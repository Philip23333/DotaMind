from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.application.chat_run_repository import ChatRunSummary
from app.application.run_recovery import RunHeartbeat, RunStaleSweeper


def test_run_heartbeat_refreshes_and_cancels_when_postgres_requests_cancel() -> None:
    async def scenario() -> None:
        repository = FakeRecoveryRepository(
            heartbeat_statuses=["running", "cancel_requested"]
        )
        cancelled = asyncio.Event()

        async def cancel() -> None:
            cancelled.set()

        heartbeat = RunHeartbeat(
            repository=repository,
            run_id=uuid4(),
            worker_id="worker-a",
            interval_seconds=0.001,
            on_cancel_requested=cancel,
        )
        await heartbeat.start()
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        await heartbeat.stop()
        assert len(repository.heartbeat_calls) == 2

    asyncio.run(scenario())


def test_stale_sweeper_uses_explicit_cutoff_and_stable_error_code() -> None:
    async def scenario() -> None:
        repository = FakeRecoveryRepository()
        sweeper = RunStaleSweeper(
            repository=repository,
            stale_after_seconds=30,
            interval_seconds=1,
        )
        reference = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
        run_ids = await sweeper.run_once(now=reference)
        assert run_ids == repository.stale_ids
        assert repository.stale_before == reference - timedelta(seconds=30)
        assert repository.stale_error_code == "stale_worker"

    asyncio.run(scenario())


class FakeRecoveryRepository:
    def __init__(self, *, heartbeat_statuses: list[str] | None = None) -> None:
        self.heartbeat_statuses = heartbeat_statuses or []
        self.heartbeat_calls: list[tuple] = []
        self.stale_ids = [uuid4()]
        self.stale_before = None
        self.stale_error_code = None

    async def update_heartbeat(self, **kwargs) -> ChatRunSummary:
        self.heartbeat_calls.append((kwargs["run_id"], kwargs["worker_id"]))
        status = self.heartbeat_statuses.pop(0) if self.heartbeat_statuses else "running"
        return _summary(status)

    async def interrupt_stale_runs(self, **kwargs):
        self.stale_before = kwargs["stale_before"]
        self.stale_error_code = kwargs["error_code"]
        return self.stale_ids


def _summary(status: str) -> ChatRunSummary:
    now = datetime.now(UTC)
    return ChatRunSummary(
        run_id=uuid4(),
        session_id=uuid4(),
        request_id=uuid4(),
        payload_hash="hash",
        user_query="query",
        status=status,
        fencing_token=1,
        worker_id="worker-a",
        last_event_sequence=0,
        result_turn_id=None,
        error_code=None,
        created_at=now,
        started_at=now,
        heartbeat_at=now,
        cancel_requested_at=None,
        completed_at=None,
    )
