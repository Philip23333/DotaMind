from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.vnext_chat_routes import router
from app.application.chat_repository import ChatIdempotencyConflictError
from app.vnext.product.chat import ProductChatCompleted


class _Service:
    async def prepare_turn(self, **kwargs):
        self.prepared = kwargs
        return kwargs

    async def stream_turn(self, _prepared):
        yield ProductChatCompleted(content="done", turn_index=1)


def test_message_route_streams_the_small_product_contract() -> None:
    service = _Service()
    app = FastAPI()
    app.include_router(router)
    app.state.vnext_chat_service = service
    session_id = uuid4()
    request_id = uuid4()

    with TestClient(app) as client:
        response = client.post(
            f"/chat/sessions/{session_id}/messages",
            headers={"X-DotaMind-Browser-Id": str(uuid4())},
            json={"request_id": str(request_id), "query": "Ame 在哪个队？"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.json() == {"type": "completed", "content": "done", "turn_index": 1}
    assert service.prepared["session_id"] == session_id


def test_message_route_requires_a_browser_identity() -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.vnext_chat_service = _Service()

    with TestClient(app) as client:
        response = client.post(
            f"/chat/sessions/{uuid4()}/messages",
            json={"request_id": str(uuid4()), "query": "question"},
        )

    assert response.status_code == 422
    assert response.json()["error_code"] == "browser_id_required"


def test_message_route_rejects_an_idempotency_payload_conflict() -> None:
    class _ConflictingService:
        async def prepare_turn(self, **_kwargs):
            raise ChatIdempotencyConflictError()

    app = FastAPI()
    app.include_router(router)
    app.state.vnext_chat_service = _ConflictingService()

    with TestClient(app) as client:
        response = client.post(
            f"/chat/sessions/{uuid4()}/messages",
            headers={"X-DotaMind-Browser-Id": str(uuid4())},
            json={"request_id": str(uuid4()), "query": "question"},
        )

    assert response.status_code == 409
    assert response.json()["error_code"] == "idempotency_conflict"
