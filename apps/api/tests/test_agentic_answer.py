from app.agentic.answer import AnswerSynthesizer
from app.agentic.evidence import build_evidence_graph
from app.agentic.models import ExecutionPlan, ToolCall, ToolResult, ToolSource


def test_answer_synthesizer_builds_counter_pick_answer() -> None:
    plan = _counter_pick_plan()
    graph = build_evidence_graph(
        plan,
        [
            _resolved_lina_result(),
            _matchup_result(match_count=100),
        ],
    )

    answer = AnswerSynthesizer().synthesize(plan, graph)

    assert answer.status == "ok"
    assert answer.answer_type == "draft_advice"
    assert answer.claims[0].claim == "Resolved target hero as Lina (hero_id=25)."
    assert answer.recommendations[0].subject == "hero_id=66"
    assert answer.recommendations[0].score == 0.55
    assert any(item.code == "not_full_draft_recommendation" for item in answer.limitations)
    assert any(item.code == "hero_name_unresolved" for item in answer.limitations)


def test_answer_synthesizer_reports_missing_matchup_evidence() -> None:
    plan = _counter_pick_plan()
    graph = build_evidence_graph(plan, [_resolved_lina_result()])

    answer = AnswerSynthesizer().synthesize(plan, graph)

    assert answer.status == "insufficient_evidence"
    assert answer.recommendations == []
    assert any("matchup_win_rate" in item.detail for item in answer.limitations)


def test_answer_synthesizer_reports_missing_sample_size() -> None:
    plan = _counter_pick_plan()
    graph = build_evidence_graph(
        plan,
        [
            _resolved_lina_result(),
            _matchup_result(match_count=None),
        ],
    )

    answer = AnswerSynthesizer().synthesize(plan, graph)

    assert answer.status == "insufficient_evidence"
    assert any("sample_size" in item.detail for item in answer.limitations)


def test_answer_synthesizer_reports_unsupported_output_contract() -> None:
    plan = ExecutionPlan(
        intent="team_report",
        goal="Explain a team.",
        output_contract="team_report_answer",
    )
    graph = build_evidence_graph(plan, [])

    answer = AnswerSynthesizer().synthesize(plan, graph)

    assert answer.status == "unsupported_output_contract"
    assert answer.confidence == 0


def test_answer_synthesizer_exposes_mock_data_note() -> None:
    plan = _counter_pick_plan()
    graph = build_evidence_graph(
        plan,
        [
            ToolResult(
                tool_call_id="resolve_target",
                tool="resolve_hero",
                status="error",
                source=ToolSource(name="Fixture", kind="fixture", status="mocked"),
                latency_ms=1,
                error="boom",
            )
        ],
    )

    answer = AnswerSynthesizer().synthesize(plan, graph)

    assert any(note.code == "mock_source_detected" for note in answer.data_notes)


def _counter_pick_plan() -> ExecutionPlan:
    return ExecutionPlan(
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


def _resolved_lina_result() -> ToolResult:
    return ToolResult(
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
                "aliases": [],
            },
        },
    )


def _matchup_result(match_count: int | None) -> ToolResult:
    row = {
        "hero_id": 66,
        "target_hero_id": 25,
        "win_rate": 0.55,
        "synergy": 2.0,
    }
    if match_count is not None:
        row["match_count"] = match_count
    return ToolResult(
        tool_call_id="get_matchups",
        tool="stratz.hero_vs_hero_matchup",
        status="ok",
        latency_ms=1,
        source=ToolSource(name="STRATZ", kind="public_graphql_api"),
        data={"hero_id": 25, "advantage": [row], "disadvantage": []},
    )
