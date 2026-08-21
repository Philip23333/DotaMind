from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.chat_run_routes import router
from app.application.chat_run_repository import (
    ChatRunCheckpointError,
    ChatRunResumeResult,
    ChatRunSummary,
)


def test_resume_route_accepts_option_id_and_keeps_run_id() -> None:
    api = FastAPI()
    api.include_router(router)
    run_id = uuid4()
    runtime = FakeRuntime(run_id)
    api.state.chat_run_runtime = runtime

    with TestClient(api) as client:
        response = client.post(
            f"/chat/runs/{run_id}/resume",
            headers={"X-DotaMind-Browser-Id": str(uuid4())},
            json={
                "checkpoint_type": "pandascore_match_selection",
                "option_id": "playoffs_2026_08_20",
            },
        )

    assert response.status_code == 202
    assert response.json()["run"]["run_id"] == str(run_id)
    assert runtime.selected == ("pandascore_match_selection", "playoffs_2026_08_20")


def test_resume_route_rejects_client_parameter_patch() -> None:
    api = FastAPI()
    api.include_router(router)
    api.state.chat_run_runtime = FakeRuntime(uuid4())

    with TestClient(api) as client:
        response = client.post(
            f"/chat/runs/{uuid4()}/resume",
            headers={"X-DotaMind-Browser-Id": str(uuid4())},
            json={
                "checkpoint_type": "pandascore_match_selection",
                "option_id": "playoffs_2026_08_20",
                "scheduled_date": "2026-08-20",
            },
        )

    assert response.status_code == 422


def test_resume_route_maps_invalid_option_to_422() -> None:
    api = FastAPI()
    api.include_router(router)
    run_id = uuid4()
    api.state.chat_run_runtime = FakeRuntime(run_id, invalid=True)

    with TestClient(api) as client:
        response = client.post(
            f"/chat/runs/{run_id}/resume",
            headers={"X-DotaMind-Browser-Id": str(uuid4())},
            json={
                "checkpoint_type": "pandascore_match_selection",
                "option_id": "unknown",
            },
        )

    assert response.status_code == 422
    assert response.json()["error_code"] == "checkpoint_option_invalid"


class FakeRuntime:
    def __init__(self, run_id, *, invalid: bool = False) -> None:
        self.run_id = run_id
        self.invalid = invalid
        self.selected = None

    async def resume_run(self, *, browser_id: str, run_id, checkpoint_type: str, option_id: str):
        if self.invalid:
            raise ChatRunCheckpointError("checkpoint_option_invalid")
        self.selected = (checkpoint_type, option_id)
        return ChatRunResumeResult(action="queued", run=_summary(run_id))


def _summary(run_id) -> ChatRunSummary:
    now = datetime.now(UTC)
    return ChatRunSummary(
        run_id=run_id,
        session_id=uuid4(),
        request_id=uuid4(),
        payload_hash="hash",
        user_query="match details",
        status="queued",
        fencing_token=None,
        worker_id=None,
        last_event_sequence=3,
        result_turn_id=None,
        error_code=None,
        created_at=now,
        started_at=now,
        heartbeat_at=None,
        cancel_requested_at=None,
        completed_at=None,
    )
