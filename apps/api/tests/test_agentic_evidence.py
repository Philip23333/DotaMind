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

