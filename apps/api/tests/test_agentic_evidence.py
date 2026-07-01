from pydantic import BaseModel

from app.agentic.evidence import EvidenceItem, build_evidence_graph
from app.agentic.models import ExecutionPlan, ToolCall, ToolResult, ToolSource
from app.agentic.tools import ToolDefinition, ToolRegistry
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings


class DebugInput(BaseModel):
    value: int = 1


def test_evidence_graph_aggregates_resolve_hero_result() -> None:
    plan = ExecutionPlan(
        intent="counter_pick",
        goal="Collect hero identity evidence.",
        output_contract="tool_results",
        tool_calls=[
            ToolCall(id="resolve_target", tool="resolve_hero", args={"query": "Lina"})
        ],
        required_evidence=["hero_identity"],
    )
    result = ToolResult(
        tool_call_id="resolve_target",
        tool="resolve_hero",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="Local", kind="local_constants"),
        data={
            "status": "resolved",
            "query": "Lina",
            "method": "exact",
            "hero": {
                "hero_id": 25,
                "name": "npc_dota_hero_lina",
                "localized_name": "Lina",
                "aliases": ["火女"],
            },
        },
    )

    graph = build_evidence_graph(plan, [result], _registry())

    assert graph.intent == "counter_pick"
    assert graph.missing == []
    assert graph.data_quality.completeness == 1.0
    assert graph.evidence[0].kind == "hero_identity"
    assert graph.evidence[0].subject == "Lina"
    assert graph.evidence[0].value["hero_id"] == 25


def test_evidence_graph_aggregates_matchup_and_sample_size() -> None:
    plan = ExecutionPlan(
        intent="counter_pick",
        goal="Collect matchup evidence.",
        output_contract="tool_results",
        tool_calls=[
            ToolCall(
                id="get_matchups",
                tool="stratz.hero_vs_hero_matchup",
                args={"hero_id": 25},
            )
        ],
        required_evidence=["matchup_win_rate", "sample_size"],
    )
    result = ToolResult(
        tool_call_id="get_matchups",
        tool="stratz.hero_vs_hero_matchup",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={
            "hero_id": 25,
            "filters": {
                "take": 10,
                "week": 1782345600,
                "bracket_basic_ids": ["DIVINE_IMMORTAL"],
                "match_limit": None,
            },
            "advantage": [
                {
                    "hero_id": 66,
                    "target_hero_id": 25,
                    "win_rate": 0.57,
                    "match_count": 247,
                    "synergy": 5.9,
                }
            ],
            "disadvantage": [],
        },
    )

    graph = build_evidence_graph(plan, [result], _registry())

    assert graph.missing == []
    assert graph.data_quality.min_sample_size == 247
    assert graph.data_quality.completeness == 1.0
    assert [item.kind for item in graph.evidence] == [
        "matchup_win_rate",
        "sample_size",
    ]
    assert graph.evidence[0].value["win_rate"] == 0.57
    assert graph.evidence[0].value["filters"]["bracket_basic_ids"] == [
        "DIVINE_IMMORTAL"
    ]
    assert graph.evidence[1].value["sample_size"] == 247
    assert graph.evidence[1].value["filters"]["week"] == 1782345600


def test_evidence_graph_reports_missing_required_evidence() -> None:
    plan = ExecutionPlan(
        intent="counter_pick",
        goal="Collect incomplete evidence.",
        output_contract="tool_results",
        required_evidence=["hero_identity", "matchup_win_rate"],
    )

    graph = build_evidence_graph(plan, [], _registry())

    assert graph.evidence == []
    assert graph.missing == ["hero_identity", "matchup_win_rate"]
    assert graph.data_quality.completeness == 0


def test_evidence_graph_keeps_utility_tool_result_without_evidence() -> None:
    plan = ExecutionPlan(
        intent="debug",
        goal="Run utility tool.",
        output_contract="tool_results",
        required_evidence=[],
    )
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="debug.utility",
            description="Does not produce evidence.",
            input_model=DebugInput,
            handler=lambda args: {"value": args.value},
        )
    )
    result = ToolResult(
        tool_call_id="utility",
        tool="debug.utility",
        status="ok",
        latency_ms=1,
        data={"value": 1},
    )

    graph = build_evidence_graph(plan, [result], registry)

    assert graph.tool_results == [result]
    assert graph.evidence == []
    assert graph.missing == []
    assert graph.data_quality.completeness == 1


def test_evidence_graph_reports_extractor_failure() -> None:
    def broken_extractor(_result: ToolResult) -> list[EvidenceItem]:
        raise ValueError("bad evidence")

    plan = ExecutionPlan(
        intent="debug",
        goal="Run broken extractor.",
        output_contract="tool_results",
        required_evidence=["debug_evidence"],
    )
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="debug.evidence",
            description="Broken evidence tool.",
            input_model=DebugInput,
            handler=lambda args: {"value": args.value},
            evidence_extractor=broken_extractor,
            evidence_kinds=("debug_evidence",),
        )
    )
    result = ToolResult(
        tool_call_id="debug",
        tool="debug.evidence",
        status="ok",
        latency_ms=1,
        data={"value": 1},
    )

    graph = build_evidence_graph(plan, [result], registry)

    assert graph.evidence == []
    assert "debug: evidence_extractor_failed: ValueError: bad evidence" in graph.missing
    assert "debug_evidence" in graph.missing


def test_evidence_graph_marks_failed_tool_and_mock_source() -> None:
    plan = ExecutionPlan(
        intent="counter_pick",
        goal="Track data quality.",
        output_contract="tool_results",
        required_evidence=["hero_identity"],
    )
    result = ToolResult(
        tool_call_id="resolve_target",
        tool="resolve_hero",
        status="error",
        latency_ms=1,
        source=ToolSource(name="Mock", kind="fixture", status="mocked"),
        error="boom",
    )

    graph = build_evidence_graph(plan, [result], _registry())

    assert graph.data_quality.mock_used is True
    assert graph.missing == ["resolve_target: tool_failed", "hero_identity"]
    assert graph.data_quality.completeness == 0


def test_evidence_graph_aggregates_lane_outcome() -> None:
    plan = ExecutionPlan(
        intent="lane_outcome",
        goal="Collect lane evidence.",
        output_contract="tool_results",
        required_evidence=["lane_outcome", "sample_size"],
    )
    result = ToolResult(
        tool_call_id="lane",
        tool="stratz.lane_outcome",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={
            "hero_id": 104,
            "is_with": True,
            "filters": {
                "week": 1782345600,
                "bracket_basic_ids": ["DIVINE_IMMORTAL"],
                "position_ids": ["POSITION_4"],
                "is_with": True,
            },
            "records": [
                {
                    "hero_id": 86,
                    "target_hero_id": 104,
                    "position": "POSITION_4",
                    "match_count": 25,
                    "match_win_rate": 0.6,
                }
            ],
        },
    )

    graph = build_evidence_graph(plan, [result], _registry())

    assert graph.missing == []
    assert graph.data_quality.min_sample_size == 25
    assert [item.kind for item in graph.evidence] == ["lane_outcome", "sample_size"]
    assert graph.evidence[0].value["filters"]["bracket_basic_ids"] == [
        "DIVINE_IMMORTAL"
    ]
    assert graph.evidence[1].value["filters"]["position_ids"] == ["POSITION_4"]


def test_evidence_graph_aggregates_opendota_team_evidence() -> None:
    plan = ExecutionPlan(
        intent="team_analysis",
        goal="Collect team evidence.",
        output_contract="team_report_answer",
        required_evidence=[
            "team_identity",
            "recent_matches",
            "current_players",
            "team_hero_usage",
            "match_detail_sample",
        ],
    )
    results = [
        ToolResult(
            tool_call_id="resolve_team",
            tool="opendota.resolve_team",
            status="ok",
            latency_ms=1,
            source=ToolSource(name="OpenDota", kind="public_api"),
            data={
                "status": "resolved",
                "query": "BB",
                "team": {"team_id": 1, "name": "BetBoom Team", "tag": "BB"},
            },
        ),
        ToolResult(
            tool_call_id="matches",
            tool="opendota.team_recent_matches",
            status="ok",
            latency_ms=1,
            source=ToolSource(name="OpenDota", kind="public_api"),
            data={
                "team_id": 1,
                "days": 30,
                "matches_in_window": 8,
                "wins": 5,
                "losses": 3,
                "recent_record": "5-3 in last 8 matches",
            },
        ),
        ToolResult(
            tool_call_id="players",
            tool="opendota.team_players",
            status="ok",
            latency_ms=1,
            source=ToolSource(name="OpenDota", kind="public_api"),
            data={"team_id": 1, "player_count": 5, "players": []},
        ),
        ToolResult(
            tool_call_id="heroes",
            tool="opendota.team_heroes",
            status="ok",
            latency_ms=1,
            source=ToolSource(name="OpenDota", kind="public_api"),
            data={"heroes": [], "match_details_analyzed": 5},
        ),
    ]

    graph = build_evidence_graph(plan, results, _registry())

    assert graph.missing == []
    assert {
        "team_identity",
        "recent_matches",
        "current_players",
        "team_hero_usage",
        "match_detail_sample",
    } <= {item.kind for item in graph.evidence}


def test_evidence_graph_aggregates_opendota_hero_stats() -> None:
    plan = ExecutionPlan(
        intent="meta_recommendation",
        goal="Collect role hero stats.",
        output_contract="meta_answer",
        required_evidence=["hero_stats", "role_fit"],
    )
    result = ToolResult(
        tool_call_id="hero_stats",
        tool="opendota.hero_stats_by_role",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="OpenDota", kind="public_api"),
        data={"role": "offlane", "hero_count": 1, "heroes": [{"hero": "Mars"}]},
    )

    graph = build_evidence_graph(plan, [result], _registry())

    assert graph.missing == []
    assert [item.kind for item in graph.evidence] == [
        "hero_stats",
        "role_fit",
        "sample_size",
    ]
    assert graph.data_quality.min_sample_size == 1


def _registry():
    return build_default_tool_registry(
        Settings(stratz_graphql_url="https://api.stratz.test/graphql", stratz_token="token")
    )
