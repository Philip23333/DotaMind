import asyncio

from app.agentic.models import ExecutionPlan, ToolCall
from app.agentic.planning.controller import AgentControllerResult
from app.agentic.planning.decisions import (
    CapabilityBoundaryDecision,
    ToolPlanDecision,
    resolve_required_evidence,
)
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.application.plan_service import PlanService
from app.core.config import get_settings


class FakeController:
    def __init__(self, result: AgentControllerResult) -> None:
        self.result = result
        self.received_history: list = []

    @property
    def prompt_versions(self) -> dict[str, str]:
        return {}

    async def decide(
        self, query: str, game: str = "dota2", recent_messages=None, **kwargs
    ) -> AgentControllerResult:
        self.received_history = list(recent_messages or [])
        return self.result


def _tool_result(plan: ExecutionPlan, reason: str) -> AgentControllerResult:
    registry = build_default_tool_registry(get_settings())
    return AgentControllerResult(
        status="decided",
        reason=reason,
        decision=ToolPlanDecision(kind="tool_plan", plan=plan),
        evidence_resolution=resolve_required_evidence(plan, registry),
    )


def test_default_plan_service_shares_one_registry_across_runtime_components() -> None:
    service = PlanService()

    assert service.controller.registry is service.registry
    assert service.runner.registry is service.registry
    assert service.runner.executor.registry is service.registry


def test_plan_service_returns_insufficient_tools_without_execution() -> None:
    service = PlanService(
        controller=FakeController(
            AgentControllerResult(
                status="decided",
                reason="no team tool is registered",
                decision=CapabilityBoundaryDecision(
                    kind="capability_boundary",
                    intent="team_recent",
                    reason="no team tool is registered",
                ),
            )
        )
    )

    service_result = asyncio.run(service.run("How Team BB play lately?"))
    assert service_result.state is not None
    result = service_result.state

    assert result.status == "insufficient_tools"
    assert result.tool_results == []
    assert result.evidence_graph is None
    assert result.answer is None
    assert result.review is None
    assert result.trace[-1].status == "completed"
    assert result.response

# End of stateless PlanService tests.
def test_plan_service_returns_error_when_planner_errors() -> None:
    service = PlanService(
        controller=FakeController(
            AgentControllerResult(
                status="error",
                reason="LLM disabled",
                failure_type="planning_error",
                errors=["DOTAMIND_LLM_ENABLED must be true"],
            )
        )
    )

    service_result = asyncio.run(service.run("enemy picked Lina"))
    assert service_result.state is not None
    result = service_result.state

    assert result.status == "error"
    assert result.errors == ["DOTAMIND_LLM_ENABLED must be true"]
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
                    # Set explicitly: this FakeController bypasses AgentController.plan()
                    # (where apply_sample_policy backfills the default), and the
                    # fixture row has match_count=100, below the policy default
                    # of 2000. A relaxed floor keeps the row so the orchestration
                    # under test produces complete evidence.
                    "min_sample_size": 100,
                },
            ),
        ],
        required_evidence=["hero_identity", "matchup_ranking_row", "sample_size"],
    )
    service = PlanService(
        controller=FakeController(
            _tool_result(plan, "matchup ranking plan")
        )
    )

    service_result = asyncio.run(service.run("enemy picked Lina, what should I pick?"))
    assert service_result.state is not None
    result = service_result.state

    assert result.status == "ok"
    assert len(result.tool_results) == 2
    assert result.evidence_graph is not None
    assert result.evidence_graph.data_quality.completeness == 1.0
    assert result.answer is not None
    assert result.answer.status == "ok"
    assert result.review is not None
    assert result.review.severity == "pass"
    assert any(event.node == "critic" for event in result.trace)
    assert result.trace[-1].node == "run_finalize"
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
        controller=FakeController(
            _tool_result(plan, "bad plan")
        )
    )

    service_result = asyncio.run(service.run("enemy picked Lina"))
    assert service_result.state is not None
    result = service_result.state

    assert result.status == "error"
    assert result.evidence_graph is None
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
        controller=FakeController(
            _tool_result(plan, "partial plan")
        )
    )

    service_result = asyncio.run(service.run("enemy picked Lina"))
    assert service_result.state is not None
    result = service_result.state

    assert result.status == "error"
    assert result.answer is None
    assert result.review is None
    assert any("not producible by selected tools" in item for item in result.errors)
    assert result.response
