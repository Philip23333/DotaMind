from uuid import UUID

from fastapi.testclient import TestClient

from app.agentic.nodes import attempt_finalize_node, response_node
from app.agentic.nodes.run_finalize import run_finalize_node
from app.agentic.nodes.run_init import run_init_node
from app.agentic.runtime.clock import SystemClock
from app.agentic.state import AgentRunState
from app.application.idempotency import IdempotencyConflictError
from app.application.plan_service import PlanServiceResult
from app.application.session_store import SessionStoreError
from app.core.config import RuntimePolicy
from app.main import app


class FakePlanService:
    def __init__(self) -> None:
        self.received_session_ids: list[UUID | None] = []
        self.received_request_ids: list[UUID | None] = []

    async def run(
        self,
        query: str,
        game: str = "dota2",
        session_id: UUID | None = None,
        request_id: UUID | None = None,
    ) -> PlanServiceResult:
        self.received_session_ids.append(session_id)
        self.received_request_ids.append(request_id)
        state = AgentRunState(
            query=query,
            game=game,
            status="insufficient_tools",
            reason="no registered team tool",
        )
        state.response = None
        clock = SystemClock()
        run_init_node(state, RuntimePolicy(), clock)
        state.add_trace("controller", "no registered team tool", "completed")
        attempt_finalize_node(state, clock)
        run_finalize_node(state, clock)
        state = response_node(state)
        response = dict(state.response or {})
        response["session_id"] = str(session_id) if session_id is not None else None
        return PlanServiceResult(
            public_response=response,
            state=state,
            idempotency_status="disabled",
        )


def test_plan_route_returns_plan_response(monkeypatch) -> None:
    from app.api.v1 import routes

    service = FakePlanService()
    monkeypatch.setattr(routes, "_plan_service", lambda _request: service)

    response = TestClient(app).post(
        "/api/v1/plan",
        json={"query": "How Team BB play lately?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "insufficient_tools"
    assert payload["response_type"] == "capability_boundary"
    # Stateless request → session_id echoed as null.
    assert payload["session_id"] is None
    assert service.received_session_ids == [None]
    assert "controller_output" not in payload
    assert "controller_raw_content" not in payload
    assert "controller_finish_reason" not in payload
    assert "controller_prompt_messages" not in payload
    assert payload["tool_results"] == []
    assert payload["evidence_graph"] is None
    assert payload["answer"] is None
    assert payload["review"] is None
    assert payload["trace"][0]["node"] == "run_init"
    assert any(event["node"] == "controller" for event in payload["trace"])
    assert payload["runtime"]["attempts"][0]["status"] == "insufficient_tools"


def test_plan_route_echoes_session_id(monkeypatch) -> None:
    from app.api.v1 import routes

    service = FakePlanService()
    monkeypatch.setattr(routes, "_plan_service", lambda _request: service)

    sid = "12345678-1234-4234-8234-123456789abc"
    response = TestClient(app).post(
        "/api/v1/plan",
        json={"query": "How Team BB play lately?", "session_id": sid},
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == sid
    assert str(service.received_session_ids[0]) == sid


def test_plan_route_rejects_invalid_session_id() -> None:
    response = TestClient(app).post(
        "/api/v1/plan",
        json={"query": "hello", "session_id": "not-a-uuid"},
    )
    assert response.status_code == 422


def test_plan_route_rejects_non_v4_session_ids() -> None:
    client = TestClient(app)
    for sid in (
        "12345678-1234-1234-8234-123456789abc",
        "00000000-0000-0000-0000-000000000000",
    ):
        response = client.post("/api/v1/plan", json={"query": "hello", "session_id": sid})
        assert response.status_code == 422


def test_plan_route_rejects_request_id_without_session_id() -> None:
    response = TestClient(app).post(
        "/api/v1/plan",
        json={"query": "hello", "request_id": "12345678-1234-4234-8234-123456789abc"},
    )

    assert response.status_code == 422


def test_plan_route_maps_idempotency_conflict_to_409(monkeypatch) -> None:
    from app.api.v1 import routes

    class ConflictPlanService:
        async def run(self, query, game, session_id, request_id):
            assert request_id is not None
            assert session_id is not None
            raise IdempotencyConflictError(
                query=query,
                game=game,
                session_id=str(session_id),
            )

    monkeypatch.setattr(
        routes,
        "_plan_service",
        lambda _request: ConflictPlanService(),
    )
    session_id = "12345678-1234-4234-8234-123456789abc"
    request_id = "22345678-1234-4234-8234-123456789abc"

    response = TestClient(app).post(
        "/api/v1/plan",
        json={"query": "hello", "session_id": session_id, "request_id": request_id},
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "idempotency_conflict"
    assert "runtime" not in response.json()


def test_plan_route_maps_session_store_error_to_503(monkeypatch) -> None:
    from app.api.v1 import routes

    class BrokenPlanService:
        async def run(self, query, game, session_id, request_id):
            raise SessionStoreError("unavailable")

    monkeypatch.setattr(routes, "_plan_service", lambda _request: BrokenPlanService())
    response = TestClient(app).post("/api/v1/plan", json={"query": "hello"})

    assert response.status_code == 503
    assert response.json()["error_code"] == "session_store_error"


def test_removed_legacy_routes_return_404() -> None:
    client = TestClient(app)

    assert client.post("/api/v1/query", json={"query": "hello"}).status_code == 404
    assert client.post("/api/v1/meta-report", json={}).status_code == 404
    assert client.post("/api/v1/patch-impact", json={}).status_code == 404
    assert client.post("/api/v1/team-report", json={}).status_code == 404
    assert client.post("/api/v1/verify-claim", json={}).status_code == 404
    assert client.get("/api/v1/services").status_code == 404
    assert client.get("/debug/chat").status_code == 404
