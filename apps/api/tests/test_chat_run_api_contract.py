from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.api.v1.chat_run_routes import run_response
from app.api.v1.chat_run_schemas import ChatRunCreateRequest
from app.application.chat_run_repository import ChatRunSummary


def test_chat_run_create_schema_requires_query_and_request_id() -> None:
    request_id = uuid4()
    request = ChatRunCreateRequest(request_id=request_id, query="  hello  ")
    assert request.request_id == request_id
    assert request.game == "dota2"


def test_chat_run_response_maps_only_public_run_metadata() -> None:
    now = datetime.now(UTC)
    summary = ChatRunSummary(
        run_id=uuid4(),
        session_id=uuid4(),
        request_id=uuid4(),
        payload_hash="private-hash",
        user_query="hello",
        status="running",
        fencing_token=9,
        worker_id="private-worker",
        last_event_sequence=3,
        result_turn_id=None,
        error_code=None,
        created_at=now,
        started_at=now,
        heartbeat_at=now,
        cancel_requested_at=None,
        completed_at=None,
    )
    response = run_response(summary)
    assert response.run_id == summary.run_id
    assert response.last_event_sequence == 3
    assert "payload_hash" not in response.model_dump()
    assert "worker_id" not in response.model_dump()
