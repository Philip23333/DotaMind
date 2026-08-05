from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agentic.runtime.streaming import PhaseStreamEvent, StatusStreamEvent
from app.api.v1.chat_run_routes import router
from app.application.chat_run_repository import ChatRunSummary
from app.application.run_event_bus import StoredRunEvent


def test_events_replay_in_sequence_and_stop_on_terminal_status() -> None:
    api = FastAPI()
    api.include_router(router)
    run_id = uuid4()
    session_id = uuid4()
    browser_id = str(uuid4())
    summary = _summary(run_id, session_id, "running")
    api.state.chat_run_repository = FakeRepository(browser_id, summary)
    api.state.chat_run_event_bus = FakeEventBus(
        [
            StoredRunEvent(
                run_id=run_id,
                session_id=session_id,
                sequence=1,
                event=PhaseStreamEvent(phase="planning", attempt_index=0),
            ),
            StoredRunEvent(
                run_id=run_id,
                session_id=session_id,
                sequence=2,
                event=StatusStreamEvent(status="completed"),
            ),
        ]
    )

    with TestClient(api) as client:
        response = client.get(
            f"/chat/runs/{run_id}/events?after=0",
            headers={"X-DotaMind-Browser-Id": browser_id},
        )
    assert response.status_code == 200
    lines = [json.loads(line) for line in response.text.splitlines()]
    assert [line["sequence"] for line in lines] == [1, 2]
    assert lines[-1]["event"]["status"] == "completed"


def test_events_synthesize_terminal_status_when_redis_stream_is_missing() -> None:
    api = FastAPI()
    api.include_router(router)
    run_id = uuid4()
    session_id = uuid4()
    browser_id = str(uuid4())
    api.state.chat_run_repository = FakeRepository(
        browser_id,
        _summary(run_id, session_id, "completed"),
    )
    api.state.chat_run_event_bus = FakeEventBus([])

    with TestClient(api) as client:
        response = client.get(
            f"/chat/runs/{run_id}/events",
            headers={"X-DotaMind-Browser-Id": browser_id},
        )
    assert response.status_code == 200
    payload = json.loads(response.text)
    assert payload["event"]["status"] == "completed"
    assert payload["event"]["transcript_recovery"] is True


class FakeRepository:
    def __init__(self, browser_id: str, summary: ChatRunSummary) -> None:
        self.browser_id = browser_id
        self.summary = summary

    async def get_run_for_browser(self, browser_id: str, run_id):
        if browser_id != self.browser_id:
            from app.application.chat_run_repository import ChatRunNotFoundError

            raise ChatRunNotFoundError()
        return self.summary


class FakeEventBus:
    def __init__(self, events: list[StoredRunEvent]) -> None:
        self.events = events
        self.reads = 0

    async def read_after(self, *, run_id, session_id, after):
        self.reads += 1
        return [event for event in self.events if event.sequence > after]

    async def wait_after(self, *, run_id, session_id, after, timeout_seconds):
        return []


def _summary(run_id, session_id, status: str) -> ChatRunSummary:
    now = datetime.now(UTC)
    return ChatRunSummary(
        run_id=run_id,
        session_id=session_id,
        request_id=uuid4(),
        payload_hash="hash",
        user_query="hello",
        status=status,
        fencing_token=1,
        worker_id="worker",
        last_event_sequence=2,
        result_turn_id=uuid4() if status == "completed" else None,
        error_code=None,
        created_at=now,
        started_at=now,
        heartbeat_at=now,
        cancel_requested_at=None,
        completed_at=now if status == "completed" else None,
    )
