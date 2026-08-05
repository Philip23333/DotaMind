from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.chat_run_routes import router
from app.application.chat_run_repository import ChatRunNotFoundError, ChatRunSummary


def test_query_and_active_run_enforce_browser_ownership() -> None:
    api = FastAPI()
    api.include_router(router)
    browser_id = str(uuid4())
    repository = FakeRunRepository(browser_id)
    api.state.chat_run_repository = repository
    session_id = uuid4()
    run_id = uuid4()
    repository.summary = _summary(run_id, session_id)

    with TestClient(api) as client:
        response = client.get(
            f"/chat/runs/{run_id}",
            headers={"X-DotaMind-Browser-Id": browser_id},
        )
        assert response.status_code == 200
        assert response.json()["run_id"] == str(run_id)

        active = client.get(
            f"/chat/sessions/{session_id}/active-run",
            headers={"X-DotaMind-Browser-Id": browser_id},
        )
        assert active.status_code == 200
        assert active.json()["run_id"] == str(run_id)

        other = client.get(
            f"/chat/runs/{run_id}",
            headers={"X-DotaMind-Browser-Id": str(uuid4())},
        )
        assert other.status_code == 404
        assert other.json()["error_code"] == "not_found"


class FakeRunRepository:
    def __init__(self, browser_id: str) -> None:
        self.browser_id = browser_id
        self.summary: ChatRunSummary | None = None

    async def get_run_for_browser(self, browser_id: str, run_id):
        if browser_id != self.browser_id:
            raise ChatRunNotFoundError()
        return self.summary

    async def get_active_run(self, browser_id: str, session_id):
        if browser_id != self.browser_id:
            raise ChatRunNotFoundError()
        return self.summary


def _summary(run_id, session_id) -> ChatRunSummary:
    now = datetime.now(UTC)
    return ChatRunSummary(
        run_id=run_id,
        session_id=session_id,
        request_id=uuid4(),
        payload_hash="hash",
        user_query="hello",
        status="running",
        fencing_token=1,
        worker_id="worker",
        last_event_sequence=2,
        result_turn_id=None,
        error_code=None,
        created_at=now,
        started_at=now,
        heartbeat_at=now,
        cancel_requested_at=None,
        completed_at=None,
    )
