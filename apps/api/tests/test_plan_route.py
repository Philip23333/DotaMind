from fastapi.testclient import TestClient

from app.agentic.nodes import attempt_finalize_node, response_node
from app.agentic.nodes.run_finalize import run_finalize_node
from app.agentic.nodes.run_init import run_init_node
from app.agentic.runtime.clock import SystemClock
from app.agentic.runtime.streaming import PhaseStreamEvent, publish_stream_event
from app.agentic.state import AgentRunState
from app.application.plan_service import PlanServiceResult
from app.core.config import RuntimePolicy
from app.main import app


class FakePlanService:
    def __init__(self) -> None:
        self.received: list[tuple[str, str]] = []

    async def run(
        self,
        query: str,
        game: str = "dota2",
    ) -> PlanServiceResult:
        self.received.append((query, game))
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
        response["session_id"] = None
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
    assert service.received == [("How Team BB play lately?", "dota2")]
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


def test_plan_route_rejects_stateful_fields(monkeypatch) -> None:
    from app.api.v1 import routes

    service = FakePlanService()
    monkeypatch.setattr(routes, "_plan_service", lambda _request: service)

    response = TestClient(app).post(
        "/api/v1/plan",
        json={"query": "How Team BB play lately?", "session_id": "ignored"},
    )

    assert response.status_code == 422
    assert service.received == []


def test_plan_route_rejects_request_id_and_session_id() -> None:
    response = TestClient(app).post(
        "/api/v1/plan",
        json={
            "query": "hello",
            "session_id": "12345678-1234-4234-8234-123456789abc",
            "request_id": "22345678-1234-4234-8234-123456789abc",
        },
    )
    assert response.status_code == 422


def test_plan_route_rejects_request_id_alone() -> None:
    response = TestClient(app).post(
        "/api/v1/plan",
        json={"query": "hello", "request_id": "12345678-1234-4234-8234-123456789abc"},
    )

    assert response.status_code == 422


def test_plan_stream_emits_safe_runtime_events_then_result(monkeypatch) -> None:
    from app.api.v1 import routes

    class StreamingPlanService(FakePlanService):
        async def run(self, query, game="dota2"):
            publish_stream_event(PhaseStreamEvent(phase="planning", attempt_index=0))
            return await super().run(query, game)

    monkeypatch.setattr(routes, "_plan_service", lambda _request: StreamingPlanService())

    response = TestClient(app).post("/api/v1/plan/stream", json={"query": "hello"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [line for line in response.text.splitlines() if line]
    assert len(events) == 2
    assert '"type":"phase"' in events[0]
    assert '"phase":"planning"' in events[0]
    assert '"type":"result"' in events[1]
    assert '"status":"insufficient_tools"' in events[1]
    assert "controller_raw_content" not in response.text


def test_plan_stream_rejects_stateful_fields() -> None:
    response = TestClient(app).post(
        "/api/v1/plan/stream",
        json={"query": "hello", "session_id": "ignored"},
    )

    assert response.status_code == 422


def test_removed_legacy_routes_return_404() -> None:
    client = TestClient(app)

    assert client.post("/api/v1/query", json={"query": "hello"}).status_code == 404
    assert client.post("/api/v1/meta-report", json={}).status_code == 404
    assert client.post("/api/v1/patch-impact", json={}).status_code == 404
    assert client.post("/api/v1/team-report", json={}).status_code == 404
    assert client.post("/api/v1/verify-claim", json={}).status_code == 404
    assert client.get("/api/v1/services").status_code == 404
    assert client.get("/debug/chat").status_code == 404
