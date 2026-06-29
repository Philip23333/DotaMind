from app.agentic.evidence import build_evidence_graph
from app.agentic.models import ExecutionPlan, ToolCall, ToolResult, ToolSource


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

    graph = build_evidence_graph(plan, [result])

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

    graph = build_evidence_graph(plan, [result])

    assert graph.missing == []
    assert graph.data_quality.min_sample_size == 247
    assert graph.data_quality.completeness == 1.0
    assert [item.kind for item in graph.evidence] == [
        "matchup_win_rate",
        "sample_size",
    ]
    assert graph.evidence[0].value["win_rate"] == 0.57
    assert graph.evidence[1].value["sample_size"] == 247


def test_evidence_graph_reports_missing_required_evidence() -> None:
    plan = ExecutionPlan(
        intent="counter_pick",
        goal="Collect incomplete evidence.",
        output_contract="tool_results",
        required_evidence=["hero_identity", "matchup_win_rate"],
    )

    graph = build_evidence_graph(plan, [])

    assert graph.evidence == []
    assert graph.missing == ["hero_identity", "matchup_win_rate"]
    assert graph.data_quality.completeness == 0


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

    graph = build_evidence_graph(plan, [result])

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

    graph = build_evidence_graph(plan, [result])

    assert graph.missing == []
    assert graph.data_quality.min_sample_size == 25
    assert [item.kind for item in graph.evidence] == ["lane_outcome", "sample_size"]


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

    graph = build_evidence_graph(plan, results)

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

    graph = build_evidence_graph(plan, [result])

    assert graph.missing == []
    assert [item.kind for item in graph.evidence] == [
        "hero_stats",
        "role_fit",
        "sample_size",
    ]
    assert graph.data_quality.min_sample_size == 1
