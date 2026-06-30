from fastapi.testclient import TestClient

from app.agentic.nodes import response_node
from app.agentic.state import AgentRunState
from app.main import app


class FakePlanService:
    async def run(self, query: str, game: str = "dota2") -> AgentRunState:
        state = AgentRunState(
            query=query,
            game=game,
            status="insufficient_tools",
            reason="no registered team tool",
        )
        state.response = None
        state.add_trace("planner", "no registered team tool", "insufficient_tools")
        return response_node(state)


def test_plan_route_returns_plan_response(monkeypatch) -> None:
    from app.api.v1 import routes

    monkeypatch.setattr(routes, "plan_service", FakePlanService())

    response = TestClient(app).post(
        "/api/v1/plan",
        json={"query": "How Team BB play lately?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "insufficient_tools"
    assert payload["response_type"] == "capability_boundary"
    assert "planner_output" in payload
    assert payload["planner_output"] is None
    assert "planner_raw_content" in payload
    assert payload["planner_raw_content"] is None
    assert "planner_finish_reason" in payload
    assert payload["planner_finish_reason"] is None
    assert payload["tool_results"] == []
    assert payload["evidence_graph"] is None
    assert payload["answer"] is None
    assert payload["review"] is None
    assert payload["trace"][0]["node"] == "planner"


def test_removed_legacy_routes_return_404() -> None:
    client = TestClient(app)

    assert client.post("/api/v1/query", json={"query": "hello"}).status_code == 404
    assert client.post("/api/v1/meta-report", json={}).status_code == 404
    assert client.post("/api/v1/patch-impact", json={}).status_code == 404
    assert client.post("/api/v1/team-report", json={}).status_code == 404
    assert client.post("/api/v1/verify-claim", json={}).status_code == 404
    assert client.get("/api/v1/services").status_code == 404
    assert client.get("/debug/chat").status_code == 404
