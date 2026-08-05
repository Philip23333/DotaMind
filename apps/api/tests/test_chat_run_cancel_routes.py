from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.chat_run_routes import router
from app.application.chat_run_repository import (
    ChatRunCancelResult,
    ChatRunSummary,
    ChatRunTerminalError,
)


def test_cancel_route_returns_202_and_reaches_runtime() -> None:
    api = FastAPI()
    api.include_router(router)
    run_id = uuid4()
    runtime = FakeRuntime(run_id)
    api.state.chat_run_runtime = runtime

    with TestClient(api) as client:
        response = client.post(
            f"/chat/runs/{run_id}/cancel",
            headers={"X-DotaMind-Browser-Id": str(uuid4())},
        )
    assert response.status_code == 200
    assert response.json()["run"]["status"] == "cancel_requested"
    assert runtime.cancelled_run_id == run_id


def test_cancel_route_maps_terminal_run_to_409() -> None:
    api = FastAPI()
    api.include_router(router)
    run_id = uuid4()
    runtime = FakeRuntime(run_id, terminal=True)
    api.state.chat_run_runtime = runtime

    with TestClient(api) as client:
        response = client.post(
            f"/chat/runs/{run_id}/cancel",
            headers={"X-DotaMind-Browser-Id": str(uuid4())},
        )
    assert response.status_code == 409
    assert response.json()["error_code"] == "run_terminal"


class FakeRuntime:
    def __init__(self, run_id, *, terminal: bool = False) -> None:
        self.run_id = run_id
        self.terminal = terminal
        self.cancelled_run_id = None

    async def cancel_run(self, *, browser_id: str, run_id):
        if self.terminal:
            raise ChatRunTerminalError()
        self.cancelled_run_id = run_id
        return ChatRunCancelResult(
            action="requested",
            run=_summary(run_id),
        )


def _summary(run_id) -> ChatRunSummary:
    now = datetime.now(UTC)
    return ChatRunSummary(
        run_id=run_id,
        session_id=uuid4(),
        request_id=uuid4(),
        payload_hash="hash",
        user_query="hello",
        status="cancel_requested",
        fencing_token=1,
        worker_id="worker",
        last_event_sequence=2,
        result_turn_id=None,
        error_code=None,
        created_at=now,
        started_at=now,
        heartbeat_at=now,
        cancel_requested_at=now,
        completed_at=None,
    )
