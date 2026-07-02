import asyncio

from pydantic import BaseModel

from app.agentic.graph import AgentGraphRunner
from app.agentic.models import ExecutionPlan, ToolCall
from app.agentic.planning.planner import AgenticPlannerResult
from app.agentic.state import AgentRunState
from app.agentic.tools import (
    AcceptedRef,
    ArgContract,
    OutputPathContract,
    ToolDefinition,
    ToolRegistry,
)
from app.agentic.tools.opendota_tools import resolve_team_evidence, team_recent_matches_evidence
from app.agentic.tools.stratz_tools import (
    hero_matchup_ranking_evidence,
    pair_lane_outcome_evidence,
    resolve_hero_evidence,
)


class HeroInput(BaseModel):
    query: str


class MatchupInput(BaseModel):
    hero_id: int
    side: str = "vs"


class PairLaneInput(BaseModel):
    hero_id: int
    partner_hero_id: int
    is_with: bool


class TeamIdInput(BaseModel):
    team_id: int
    days: int = 30


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
            ToolCall(id="t1", tool="resolve_hero", args={"query": "Lina"}),
            ToolCall(id="t1", tool="resolve_hero", args={"query": "Lina"}),
        ],
        required_evidence=["hero_identity"],
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
                },
            ),
        ],
        required_evidence=["hero_identity", "matchup_ranking_row", "sample_size"],
    )

    state = asyncio.run(_runner(plan).run(AgentRunState(query="debug", game="dota2")))

    assert state.status == "ok"
    assert state.answer
    assert state.answer.status == "ok"
    assert state.review
    assert state.review.severity == "pass"
    assert state.response
    assert state.response_type == "natural_language_answer"


def test_graph_team_evidence_reaches_unsupported_answer_response() -> None:
    plan = ExecutionPlan(
        intent="team_analysis",
        goal="Collect team evidence.",
        output_contract="team_recent_report",
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
    assert state.answer.status == "ok"
    assert state.response_type == "team_recent_report"


def test_graph_lane_outcome_plan_generates_lane_evidence() -> None:
    plan = ExecutionPlan(
        intent="pair_lane_outcome",
        goal="Fetch pair lane outcome evidence.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="resolve_sk", tool="resolve_hero", args={"query": "骷髅王"}),
            ToolCall(id="resolve_aa", tool="resolve_hero", args={"query": "冰魂"}),
            ToolCall(
                id="pair_lane",
                tool="stratz.pair_lane_outcome",
                args={
                    "hero_id": "$resolve_sk.data.hero.hero_id",
                    "partner_hero_id": "$resolve_aa.data.hero.hero_id",
                    "is_with": True,
                },
            ),
        ],
        required_evidence=["hero_identity", "pair_lane_winrate", "sample_size"],
    )

    state = asyncio.run(_runner(plan).run(AgentRunState(query="debug", game="dota2")))

    assert state.status == "ok"
    assert state.evidence_graph
    assert "pair_lane_winrate" in {item.kind for item in state.evidence_graph.evidence}
    assert state.answer
    assert state.answer.status == "ok"


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
            handler=lambda args, context: {
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
            output_paths={
                "hero_id": OutputPathContract(
                    path="data.hero.hero_id",
                    type="int",
                )
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="stratz.hero_matchup_ranking",
            description="Return fake matchup ranking evidence.",
            input_model=MatchupInput,
            handler=lambda args, context: {
                "hero_id": args.hero_id,
                "side": "vs",
                "advantage": [
                    {
                        "hero_id": 66,
                        "target_hero_id": args.hero_id,
                        "match_count": 100,
                        "win_rate": 0.55,
                    }
                ],
                "disadvantage": [],
                "filters": {"take": 10, "min_sample_size": 100},
            },
            evidence_extractor=hero_matchup_ranking_evidence,
            evidence_kinds=("matchup_ranking_row", "sample_size"),
            arg_contracts={
                "hero_id": ArgContract(
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="resolve_hero",
                            path="data.hero.hero_id",
                            type="int",
                        ),
                    )
                )
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="stratz.pair_lane_outcome",
            description="Return fake pair lane evidence.",
            input_model=PairLaneInput,
            handler=lambda args, context: {
                "hero_id": args.hero_id,
                "partner_hero_id": args.partner_hero_id,
                "is_with": args.is_with,
                "pair_record": {
                    "hero_id": args.partner_hero_id,
                    "target_hero_id": args.hero_id,
                    "position": "POSITION_2",
                    "match_count": 25,
                    "match_win_rate": 0.52,
                },
                "filters": {},
            },
            evidence_extractor=pair_lane_outcome_evidence,
            evidence_kinds=("pair_lane_winrate", "sample_size"),
            arg_contracts={
                "hero_id": ArgContract(
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="resolve_hero",
                            path="data.hero.hero_id",
                            type="int",
                        ),
                    )
                ),
                "partner_hero_id": ArgContract(
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="resolve_hero",
                            path="data.hero.hero_id",
                            type="int",
                        ),
                    )
                ),
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="opendota.resolve_team",
            description="Resolve a fake team.",
            input_model=HeroInput,
            handler=lambda args, context: {
                "status": "resolved",
                "query": args.query,
                "team": {"team_id": 1, "name": "BetBoom Team", "tag": "BB"},
            },
            evidence_extractor=resolve_team_evidence,
            evidence_kinds=("team_identity",),
            output_paths={
                "team_id": OutputPathContract(
                    path="data.team.team_id",
                    type="int",
                )
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="opendota.team_recent_matches",
            description="Return fake team matches.",
            input_model=TeamIdInput,
            handler=lambda args, context: {
                "team_id": args.team_id,
                "matches_in_window": 5,
                "wins": 3,
                "losses": 2,
                "recent_record": "3-2 in last 5 matches",
            },
            evidence_extractor=team_recent_matches_evidence,
            evidence_kinds=("recent_matches", "sample_size"),
            arg_contracts={
                "team_id": ArgContract(
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="opendota.resolve_team",
                            path="data.team.team_id",
                            type="int",
                        ),
                    )
                )
            },
        )
    )
    return registry
