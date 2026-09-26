from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.vnext_chat_routes import router, trace_router
from app.vnext.product.chat import ProductTraceSummary
from app.vnext.product.trace_store import TraceNotFoundError


class _Service:
    prepared = None

    async def prepare_turn(self, **kwargs):
        self.prepared = kwargs
        return kwargs

    async def list_session_traces(self, **kwargs):
        self.listed = kwargs
        return [
            ProductTraceSummary(
                trace_id="trace-1",
                request_id="request-1",
                status="completed",
                recording_mode="test",
                created_at="2026-09-23T00:00:00Z",
                expires_at="2026-09-26T00:00:00Z",
            )
        ]


def test_legacy_message_route_is_removed_without_starting_a_run() -> None:
    service = _Service()
    app = FastAPI()
    app.include_router(router)
    app.state.vnext_chat_service = service
    session_id = uuid4()

    with TestClient(app) as client:
        response = client.post(
            f"/chat/sessions/{session_id}/messages",
            headers={"X-DotaMind-Browser-Id": str(uuid4())},
            json={"request_id": str(uuid4()), "query": "Ame 在哪个队？"},
        )

    assert not response.is_success
    assert service.prepared is None


def test_session_trace_list_is_metadata_only_and_scoped_to_request_session() -> None:
    service = _Service()
    app = FastAPI()
    app.include_router(router)
    app.state.vnext_chat_service = service
    browser_id = str(uuid4())
    session_id = uuid4()

    with TestClient(app) as client:
        response = client.get(
            f"/chat/sessions/{session_id}/traces",
            headers={"X-DotaMind-Browser-Id": browser_id},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert service.listed == {"browser_id": browser_id, "session_id": session_id}
    assert response.json() == {
        "traces": [
            {
                "trace_id": "trace-1",
                "request_id": "request-1",
                "status": "completed",
                "recording_mode": "test",
                "created_at": "2026-09-23T00:00:00Z",
                "expires_at": "2026-09-26T00:00:00Z",
            }
        ]
    }


def test_expired_trace_download_returns_gone() -> None:
    class _ExpiredTraceService:
        async def download_trace_bundle(self, **_kwargs):
            raise TraceNotFoundError("expired")

    app = FastAPI()
    app.include_router(trace_router)
    app.state.vnext_chat_service = _ExpiredTraceService()

    with TestClient(app) as client:
        response = client.get(
            "/chat/traces/expired",
            headers={"X-DotaMind-Browser-Id": str(uuid4())},
        )

    assert response.status_code == 410
    assert response.json()["error_code"] == "trace_expired"
