from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.chat_run_routes import router
from app.application.chat_run_repository import (
    ChatRunCancelResult,
    ChatRunCreateResult,
    ChatRunResumeResult,
    ChatRunSummary,
)
from app.application.chat_run_runtime import ChatRunRuntime


def test_runtime_creates_queued_run_and_dispatches_same_preallocated_id() -> None:
    async def scenario() -> None:
        repository = FakeRepository()
        manager = FakeManager()
        runtime = ChatRunRuntime(
            repository=repository,
            manager=manager,
            executor=object(),
        )
        result = await runtime.create_run(
            browser_id=str(uuid4()),
            session_id=uuid4(),
            request_id=uuid4(),
            query="hello",
            game="dota2",
        )
        assert result.action == "created"
        assert manager.submitted == [result.run.run_id]
        assert repository.created_run_id == result.run.run_id

    asyncio.run(scenario())


def test_runtime_replay_does_not_dispatch_a_second_task() -> None:
    async def scenario() -> None:
        repository = FakeRepository(action="replayed")
        manager = FakeManager()
        runtime = ChatRunRuntime(
            repository=repository,
            manager=manager,
            executor=object(),
        )
        result = await runtime.create_run(
            browser_id=str(uuid4()),
            session_id=uuid4(),
            request_id=uuid4(),
            query="hello",
            game="dota2",
        )
        assert result.action == "replayed"
        assert manager.submitted == []

    asyncio.run(scenario())


def test_runtime_persists_cancel_before_local_wakeup_and_redis_notice() -> None:
    async def scenario() -> None:
        calls: list[str] = []
        run_id = uuid4()
        repository = FakeCancelRepository(calls, run_id)
        manager = FakeCancelManager(calls)
        bus = FakeCancelBus(calls)
        runtime = ChatRunRuntime(
            repository=repository,
            manager=manager,
            executor=object(),
            event_bus=bus,
        )
        result = await runtime.cancel_run(browser_id=str(uuid4()), run_id=run_id)
        assert result.action == "requested"
        assert calls == ["request_cancel", "local_cancel", "publish_cancel"]

    asyncio.run(scenario())


def test_runtime_resumes_same_run_after_checkpoint_validation() -> None:
    async def scenario() -> None:
        run_id = uuid4()
        repository = FakeResumeRepository(run_id)
        manager = FakeManager()
        runtime = ChatRunRuntime(
            repository=repository,
            manager=manager,
            executor=object(),
        )

        result = await runtime.resume_run(
            browser_id=str(uuid4()),
            run_id=run_id,
            checkpoint_type="pandascore_match_selection",
            option_id="playoffs_2026_08_20",
        )

        assert result.run.run_id == run_id
        assert manager.submitted == [run_id]
        assert repository.args == {
            "checkpoint_type": "pandascore_match_selection",
            "option_id": "playoffs_2026_08_20",
        }

    asyncio.run(scenario())


def test_create_run_route_returns_202_and_validates_browser_uuid() -> None:
    api = FastAPI()
    api.include_router(router)
    runtime = FakeHttpRuntime()
    api.state.chat_run_runtime = runtime
    session_id = uuid4()
    with TestClient(api) as client:
        response = client.post(
            f"/chat/sessions/{session_id}/runs",
            headers={"X-DotaMind-Browser-Id": str(uuid4())},
            json={"request_id": str(uuid4()), "query": "hello"},
        )
        assert response.status_code == 202
        assert response.json()["run"]["status"] == "queued"

        invalid = client.post(
            f"/chat/sessions/{session_id}/runs",
            headers={"X-DotaMind-Browser-Id": "not-a-uuid"},
            json={"request_id": str(uuid4()), "query": "hello"},
        )
        assert invalid.status_code == 422
        assert invalid.json()["error_code"] == "browser_id_invalid"


class FakeManager:
    def __init__(self) -> None:
        self.submitted: list = []

    async def submit(self, run_id, runner) -> None:
        self.submitted.append(run_id)


class FakeCancelManager:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def cancel(self, run_id) -> bool:
        self.calls.append("local_cancel")
        return True


class FakeCancelRepository:
    def __init__(self, calls: list[str], run_id) -> None:
        self.calls = calls
        self.run_id = run_id

    async def request_cancel(self, **kwargs) -> ChatRunCancelResult:
        self.calls.append("request_cancel")
        return ChatRunCancelResult(
            action="requested",
            run=_summary(self.run_id, uuid4(), "created"),
        )


class FakeCancelBus:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def publish_cancel(self, **kwargs) -> None:
        self.calls.append("publish_cancel")


class FakeResumeRepository:
    def __init__(self, run_id) -> None:
        self.run_id = run_id
        self.args = None

    async def resume_checkpoint(self, **kwargs) -> ChatRunResumeResult:
        self.args = {
            "checkpoint_type": kwargs["checkpoint_type"],
            "option_id": kwargs["option_id"],
        }
        return ChatRunResumeResult(
            action="queued",
            run=_summary(self.run_id, uuid4(), "created"),
        )


class FakeRepository:
    def __init__(self, *, action: str = "created") -> None:
        self.action = action
        self.created_run_id = None
        self.failed = []

    async def create_or_get_run(self, **kwargs) -> ChatRunCreateResult:
        self.created_run_id = kwargs["run_id"]
        return ChatRunCreateResult(
            action=self.action,
            run=_summary(kwargs["run_id"], kwargs["session_id"], self.action),
        )

    async def mark_failed(self, **kwargs) -> ChatRunSummary:
        self.failed.append(kwargs)
        return _summary(self.created_run_id, uuid4(), "failed")


class FakeHttpRuntime:
    async def create_run(self, **kwargs) -> ChatRunCreateResult:
        return ChatRunCreateResult(
            action="created",
            run=_summary(uuid4(), kwargs["session_id"], "created"),
        )


def _summary(run_id, session_id, action: str) -> ChatRunSummary:
    now = datetime.now(UTC)
    status = "queued" if action in {"created", "replayed"} else "failed"
    return ChatRunSummary(
        run_id=run_id,
        session_id=session_id,
        request_id=uuid4(),
        payload_hash="hash",
        user_query="hello",
        status=status,
        fencing_token=None,
        worker_id=None,
        last_event_sequence=0,
        result_turn_id=None,
        error_code=None,
        created_at=now,
        started_at=None,
        heartbeat_at=None,
        cancel_requested_at=None,
        completed_at=None,
    )
