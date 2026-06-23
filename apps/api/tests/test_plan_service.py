import asyncio

from app.agentic.models import ExecutionPlan, ToolCall
from app.agentic.planner import AgenticPlannerResult
from app.application.plan_service import PlanService


class FakePlanner:
    def __init__(self, result: AgenticPlannerResult) -> None:
        self.result = result

    async def plan(self, query: str, game: str = "dota2") -> AgenticPlannerResult:
        return self.result


def test_plan_service_returns_insufficient_tools_without_execution() -> None:
    service = PlanService(
        planner=FakePlanner(
            AgenticPlannerResult(
                status="insufficient_tools",
                reason="no team tool is registered",
            )
        )
    )

    result = asyncio.run(service.run("How Team BB play lately?"))

    assert result.status == "insufficient_tools"
    assert result.tool_results == []
    assert result.evidence_graph is None


def test_plan_service_returns_error_when_planner_errors() -> None:
    service = PlanService(
        planner=FakePlanner(
            AgenticPlannerResult(
                status="error",
                reason="LLM disabled",
                errors=["METAMIND_LLM_ENABLED must be true"],
            )
        )
    )

    result = asyncio.run(service.run("enemy picked Lina"))

    assert result.status == "error"
    assert result.errors == ["METAMIND_LLM_ENABLED must be true"]


def test_plan_service_executes_planned_counter_pick(monkeypatch) -> None:
    class FakeTransport:
        def __init__(self, graphql_url: str, token: str) -> None:
            self.graphql_url = graphql_url
            self.token = token

        async def aclose(self) -> None:
            return None

    class FakeHeroes:
        def __init__(self, transport: FakeTransport) -> None:
            self.transport = transport

        async def hero_vs_hero_matchup(self, *args, **kwargs) -> dict:
            return {
                "hero_id": 25,
                "advantage": [
                    {
                        "hero_id": 66,
                        "target_hero_id": 25,
                        "match_count": 100,
                        "win_rate": 0.55,
                        "synergy": 2.0,
                    }
                ],
                "disadvantage": [],
            }

    monkeypatch.setattr("app.agentic.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.stratz_tools.StratzHeroes", FakeHeroes)

    plan = ExecutionPlan(
        intent="counter_pick",
        goal="Fetch Lina matchup evidence.",
        output_contract="tool_results",
        tool_calls=[
            ToolCall(id="resolve_target", tool="resolve_hero", args={"query": "Lina"}),
            ToolCall(
                id="get_matchups",
                tool="stratz.hero_vs_hero_matchup",
                args={
                    "hero_id": "$resolve_target.data.hero.hero_id",
                    "take": 3,
                },
            ),
        ],
        required_evidence=["hero_identity", "matchup_win_rate", "sample_size"],
    )
    service = PlanService(
        planner=FakePlanner(
            AgenticPlannerResult(
                status="planned",
                reason="counter plan",
                plan=plan,
            )
        )
    )

    result = asyncio.run(service.run("enemy picked Lina, what should I pick?"))

    assert result.status == "ok"
    assert len(result.tool_results) == 2
    assert result.evidence_graph is not None
    assert result.evidence_graph.data_quality.completeness == 1.0
