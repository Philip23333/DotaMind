import asyncio

from pydantic import BaseModel

from app.agentic.graph import AgentGraphRunner
from app.agentic.models import ExecutionPlan, ToolCall
from app.agentic.planning.planner import AgenticPlannerResult
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolDefinition, ToolRegistry
from app.agentic.tools.opendota_tools import resolve_team_evidence, team_recent_matches_evidence
from app.agentic.tools.stratz_tools import (
    hero_matchup_evidence,
    lane_outcome_evidence,
    resolve_hero_evidence,
)


class HeroInput(BaseModel):
    query: str


class MatchupInput(BaseModel):
    hero_id: int


class TeamIdInput(BaseModel):
    team_id: int


class FakePlanner:
    def __init__(self, result: AgenticPlannerResult) -> None:
        self.result = result

    async def plan(self, query: str, game: str = "dota2") -> AgenticPlannerResult:
        return self.result


def test_graph_stops_when_tools_are_insufficient() -> None:
    state = asyncio.run(
        AgentGraphRunner(
            FakePlanner(
                AgenticPlannerResult(
                    status="insufficient_tools",
                    reason="no team tool",
                )
            ),
            ToolRegistry(),
        ).run(AgentRunState(query="How Team BB play?", game="dota2"))
    )

    assert state.status == "insufficient_tools"
    assert state.tool_results == []
    assert state.answer is None
    assert state.response
    assert state.response_type == "capability_boundary"


def test_graph_validation_error_stops_before_tools() -> None:
    plan = ExecutionPlan(
        intent="debug",
        goal="Duplicate call ids.",
        output_contract="tool_results",
        tool_calls=[
            ToolCall(id="t1", tool="debug.hero", args={"query": "Lina"}),
            ToolCall(id="t1", tool="debug.hero", args={"query": "Lina"}),
        ],
    )

    state = asyncio.run(_runner(plan).run(AgentRunState(query="debug", game="dota2")))

    assert state.status == "error"
    assert state.tool_results == []
    assert state.evidence_graph
    assert "duplicate tool call id" in state.errors[0]


def test_graph_tool_error_still_builds_evidence_graph() -> None:
    plan = ExecutionPlan(
        intent="counter_pick",
        goal="Call missing tool.",
        output_contract="draft_advice",
        tool_calls=[ToolCall(id="missing", tool="debug.missing", args={})],
        required_evidence=["hero_identity"],
    )

    state = asyncio.run(_runner(plan).run(AgentRunState(query="debug", game="dota2")))

    assert state.status == "error"
    assert state.evidence_graph
    assert state.answer is None
    assert state.response
    assert state.response_type == "execution_error"


def test_graph_success_reaches_answer_review_and_response() -> None:
    plan = ExecutionPlan(
        intent="counter_pick",
        goal="Fetch Lina matchup evidence.",
        output_contract="draft_advice",
        tool_calls=[
            ToolCall(id="resolve_target", tool="resolve_hero", args={"query": "Lina"}),
            ToolCall(
                id="get_matchups",
                tool="stratz.hero_vs_hero_matchup",
                args={"hero_id": "$resolve_target.data.hero.hero_id"},
            ),
        ],
        required_evidence=["hero_identity", "matchup_win_rate", "sample_size"],
    )

    state = asyncio.run(_runner(plan).run(AgentRunState(query="debug", game="dota2")))

    assert state.status == "ok"
    assert state.answer
    assert state.answer.status == "ok"
    assert state.review
    assert state.review.severity == "pass"
    assert state.response
    assert state.response_type == "draft_advice"


def test_graph_team_evidence_reaches_unsupported_answer_response() -> None:
    plan = ExecutionPlan(
        intent="team_analysis",
        goal="Collect team evidence.",
        output_contract="team_report_answer",
        tool_calls=[
            ToolCall(id="resolve_team", tool="opendota.resolve_team", args={"query": "BB"}),
            ToolCall(
                id="matches",
                tool="opendota.team_recent_matches",
                args={"team_id": "$resolve_team.data.team.team_id", "days": 30},
            ),
        ],
        required_evidence=["team_identity", "recent_matches"],
    )

    state = asyncio.run(_runner(plan).run(AgentRunState(query="debug", game="dota2")))

    assert state.status == "ok"
    assert state.evidence_graph
    assert state.evidence_graph.missing == []
    assert state.answer
    assert state.answer.status == "unsupported_output_contract"
    assert state.response_type == "unsupported_answer"


def test_graph_lane_outcome_plan_generates_lane_evidence() -> None:
    plan = ExecutionPlan(
        intent="lane_outcome",
        goal="Fetch lane outcome evidence.",
        output_contract="draft_advice",
        tool_calls=[
            ToolCall(id="resolve_target", tool="resolve_hero", args={"query": "Lina"}),
            ToolCall(
                id="lane",
                tool="stratz.lane_outcome",
                args={
                    "hero_id": "$resolve_target.data.hero.hero_id",
                    "is_with": False,
                },
            ),
        ],
        required_evidence=["hero_identity", "lane_outcome", "sample_size"],
    )

    state = asyncio.run(_runner(plan).run(AgentRunState(query="debug", game="dota2")))

    assert state.status == "ok"
    assert state.evidence_graph
    assert "lane_outcome" in {item.kind for item in state.evidence_graph.evidence}
    assert state.answer
    assert state.answer.status == "unsupported_output_contract"


def _runner(plan: ExecutionPlan) -> AgentGraphRunner:
    return AgentGraphRunner(
        FakePlanner(AgenticPlannerResult(status="planned", reason="planned", plan=plan)),
        _registry(),
    )


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="resolve_hero",
            description="Resolve a fake hero.",
            input_model=HeroInput,
            handler=lambda args: {
                "status": "resolved",
                "query": args.query,
                "method": "exact",
                "hero": {
                    "hero_id": 25,
                    "name": "npc_dota_hero_lina",
                    "localized_name": "Lina",
                    "aliases": [],
                },
            },
            evidence_extractor=resolve_hero_evidence,
            evidence_kinds=("hero_identity",),
        )
    )
    registry.register(
        ToolDefinition(
            name="stratz.hero_vs_hero_matchup",
            description="Return fake matchup evidence.",
            input_model=MatchupInput,
            handler=lambda args: {
                "hero_id": args.hero_id,
                "advantage": [
                    {
                        "hero_id": 66,
                        "target_hero_id": args.hero_id,
                        "match_count": 100,
                        "win_rate": 0.55,
                    }
                ],
                "disadvantage": [],
            },
            evidence_extractor=hero_matchup_evidence,
            evidence_kinds=("matchup_win_rate", "sample_size"),
        )
    )
    registry.register(
        ToolDefinition(
            name="stratz.lane_outcome",
            description="Return fake lane evidence.",
            input_model=MatchupInput,
            handler=lambda args: {
                "hero_id": args.hero_id,
                "is_with": False,
                "records": [
                    {
                        "hero_id": 66,
                        "target_hero_id": args.hero_id,
                        "position": "POSITION_2",
                        "match_count": 25,
                        "match_win_rate": 0.52,
                    }
                ],
            },
            evidence_extractor=lane_outcome_evidence,
            evidence_kinds=("lane_outcome", "sample_size"),
        )
    )
    registry.register(
        ToolDefinition(
            name="opendota.resolve_team",
            description="Resolve a fake team.",
            input_model=HeroInput,
            handler=lambda args: {
                "status": "resolved",
                "query": args.query,
                "team": {"team_id": 1, "name": "BetBoom Team", "tag": "BB"},
            },
            evidence_extractor=resolve_team_evidence,
            evidence_kinds=("team_identity",),
        )
    )
    registry.register(
        ToolDefinition(
            name="opendota.team_recent_matches",
            description="Return fake team matches.",
            input_model=TeamIdInput,
            handler=lambda args: {
                "team_id": args.team_id,
                "matches_in_window": 5,
                "wins": 3,
                "losses": 2,
                "recent_record": "3-2 in last 5 matches",
            },
            evidence_extractor=team_recent_matches_evidence,
            evidence_kinds=("recent_matches", "sample_size"),
        )
    )
    return registry
