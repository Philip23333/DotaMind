from fastapi.testclient import TestClient

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
        state.add_trace("planner", "no registered team tool", "insufficient_tools")
        return state


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
    assert payload["tool_results"] == []
    assert payload["evidence_graph"] is None
    assert payload["answer"] is None
    assert payload["review"] is None
    assert payload["trace"][0]["node"] == "planner"
