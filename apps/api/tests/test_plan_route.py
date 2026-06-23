from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.agentic.models import ExecutionPlan
from app.main import app


@dataclass(frozen=True)
class FakePlanServiceResult:
    query: str
    game: str
    status: str
    reason: str
    plan: ExecutionPlan | None
    tool_results: list
    evidence_graph: object | None
    errors: list[str]


class FakePlanService:
    async def run(self, query: str, game: str = "dota2") -> FakePlanServiceResult:
        return FakePlanServiceResult(
            query=query,
            game=game,
            status="insufficient_tools",
            reason="no registered team tool",
            plan=None,
            tool_results=[],
            evidence_graph=None,
            errors=[],
        )


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
