import asyncio

from app.agentic.models import ExecutionPlan, ToolCall
from app.agentic.planning.planner import AgenticPlannerResult
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
    assert result.answer is None
    assert result.review is None
    assert result.trace[-1].status == "insufficient_tools"
    assert result.response


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
    assert result.answer is None
    assert result.review is None
    assert result.response


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
                        "matchup_win_rate": 0.55,
                        "synergy": 2.0,
                    }
                ],
                "disadvantage": [],
            }

        async def lane_outcome(self, *args, **kwargs) -> list:
            return []

        async def hero_position_stats(self, *args, **kwargs) -> list:
            return []

    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzTransport", FakeTransport)
    monkeypatch.setattr("app.agentic.tools.stratz_tools.StratzHeroes", FakeHeroes)

    plan = ExecutionPlan(
        intent="hero_matchup_ranking",
        goal="Fetch Lina matchup ranking evidence.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="resolve_target", tool="resolve_hero", args={"query": "Lina"}),
            ToolCall(
                id="get_ranking",
                tool="stratz.hero_matchup_ranking",
                args={
                    "hero_id": "$resolve_target.data.hero.hero_id",
                    "side": "vs",
                    "take": 3,
                },
            ),
        ],
        required_evidence=["hero_identity", "matchup_ranking_row", "sample_size"],
    )
    service = PlanService(
        planner=FakePlanner(
            AgenticPlannerResult(
                status="planned",
                reason="matchup ranking plan",
                plan=plan,
            )
        )
    )

    result = asyncio.run(service.run("enemy picked Lina, what should I pick?"))

    assert result.status == "ok"
    assert len(result.tool_results) == 2
    assert result.evidence_graph is not None
    assert result.evidence_graph.data_quality.completeness == 1.0
    assert result.answer is not None
    assert result.answer.status == "ok"
    assert result.review is not None
    assert result.review.severity == "pass"
    assert result.trace[-1].node == "critic"
    assert result.response


def test_plan_service_returns_error_without_answer_when_runner_fails() -> None:
    plan = ExecutionPlan(
        intent="hero_matchup_ranking",
        goal="Bad plan.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(
                id="get_ranking",
                tool="stratz.hero_matchup_ranking",
                args={"hero_id": "$missing.data.hero.hero_id", "side": "vs"},
            )
        ],
        required_evidence=["matchup_ranking_row"],
    )
    service = PlanService(
        planner=FakePlanner(
            AgenticPlannerResult(
                status="planned",
                reason="bad plan",
                plan=plan,
            )
        )
    )

    result = asyncio.run(service.run("enemy picked Lina"))

    assert result.status == "error"
    assert result.evidence_graph is not None
    assert result.answer is None
    assert result.review is None
    assert result.errors
    assert result.response


def test_plan_service_rejects_unproducible_required_evidence() -> None:
    plan = ExecutionPlan(
        intent="hero_matchup_ranking",
        goal="Only resolve Lina.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="resolve_target", tool="resolve_hero", args={"query": "Lina"})
        ],
        required_evidence=["hero_identity", "matchup_ranking_row", "sample_size"],
    )
    service = PlanService(
        planner=FakePlanner(
            AgenticPlannerResult(
                status="planned",
                reason="partial plan",
                plan=plan,
            )
        )
    )

    result = asyncio.run(service.run("enemy picked Lina"))

    assert result.status == "error"
    assert result.answer is None
    assert result.review is None
    assert any("not producible by selected tools" in item for item in result.errors)
    assert result.response
