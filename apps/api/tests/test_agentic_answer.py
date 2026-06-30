import asyncio
from typing import Any

from app.agentic.answer import AnswerSynthesizer
from app.agentic.evidence import build_evidence_graph
from app.agentic.models import ExecutionPlan, ToolCall, ToolResult, ToolSource
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings
from app.llm.provider import ToolCallResult


def test_answer_synthesizer_builds_counter_pick_answer() -> None:
    plan = _counter_pick_plan()
    graph = build_evidence_graph(
        plan,
        [
            _resolved_lina_result(),
            _matchup_result(match_count=100),
        ],
        _registry(),
    )

    answer = _synthesize(plan, graph)

    assert answer.status == "ok"
    assert answer.answer_type == "draft_advice"
    assert answer.claims[0].claim == "Resolved target hero as Lina (hero_id=25)."
    assert answer.recommendations[0].subject == "hero_id=66"
    assert answer.recommendations[0].score == 0.55
    assert any(item.code == "not_full_draft_recommendation" for item in answer.limitations)
    assert any(item.code == "hero_name_unresolved" for item in answer.limitations)


def test_answer_synthesizer_reports_missing_matchup_evidence() -> None:
    plan = _counter_pick_plan()
    graph = build_evidence_graph(plan, [_resolved_lina_result()], _registry())

    answer = _synthesize(plan, graph)

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
        _registry(),
    )

    answer = _synthesize(plan, graph)

    assert answer.status == "insufficient_evidence"
    assert any("sample_size" in item.detail for item in answer.limitations)


def test_answer_synthesizer_reports_unsupported_output_contract() -> None:
    plan = ExecutionPlan(
        intent="team_report",
        goal="Explain a team.",
        output_contract="team_report_answer",
    )
    graph = build_evidence_graph(plan, [], _registry())

    answer = _synthesize(plan, graph)

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
        _registry(),
    )

    answer = _synthesize(plan, graph)

    assert any(note.code == "mock_source_detected" for note in answer.data_notes)


def test_answer_synthesizer_builds_patch_impact_report() -> None:
    plan = ExecutionPlan(
        intent="patch_impact",
        goal="Summarize latest patch.",
        output_contract="patch_impact_report",
        required_evidence=["patch_records"],
    )
    graph = build_evidence_graph(
        plan,
        [
            ToolResult(
                tool_call_id="patch",
                tool="patch.get_records",
                status="ok",
                latency_ms=1,
                source=ToolSource(name="Local", kind="local_json"),
                data={
                    "patch": "7.41d",
                    "released_at": "2026-06-05",
                    "changes": [],
                    "change_count": 3,
                    "buff_count": 2,
                    "nerf_count": 1,
                },
            )
        ],
        _registry(),
    )

    answer = _synthesize(plan, graph)

    assert answer.status == "ok"
    assert answer.answer_type == "patch_impact_report"
    assert "7.41d" in answer.summary


def test_answer_synthesizer_builds_role_meta_report() -> None:
    plan = ExecutionPlan(
        intent="role_meta",
        goal="Find strong offlane heroes.",
        output_contract="role_meta_report",
        required_evidence=["hero_stats"],
    )
    graph = build_evidence_graph(
        plan,
        [
            ToolResult(
                tool_call_id="meta",
                tool="opendota.hero_stats_by_role",
                status="ok",
                latency_ms=1,
                source=ToolSource(name="OpenDota", kind="public_api"),
                data={
                    "role": "offlane",
                    "hero_count": 1,
                    "heroes": [{"localized_name": "Tidehunter", "win_rate": 0.55}],
                },
            )
        ],
        _registry(),
    )

    answer = _synthesize(plan, graph)

    assert answer.status == "ok"
    assert answer.recommendations[0].subject == "Tidehunter"
    assert graph.data_quality.min_sample_size == 1


def test_answer_synthesizer_natural_language_answer_uses_llm() -> None:
    plan = ExecutionPlan(
        intent="freeform",
        goal="Answer from evidence.",
        output_contract="natural_language_answer",
    )
    graph = build_evidence_graph(plan, [], _registry())

    answer = asyncio.run(
        AnswerSynthesizer(llm=FakeLLM(), llm_enabled=True).synthesize(plan, graph)
    )

    assert answer.status == "ok"
    assert answer.summary == "Grounded answer."


def test_answer_synthesizer_natural_language_answer_errors_when_llm_disabled() -> None:
    plan = ExecutionPlan(
        intent="freeform",
        goal="Answer from evidence.",
        output_contract="natural_language_answer",
    )
    graph = build_evidence_graph(plan, [], _registry())

    answer = asyncio.run(AnswerSynthesizer(llm_enabled=False).synthesize(plan, graph))

    assert answer.status == "error"
    assert answer.confidence == 0


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


def _synthesize(plan: ExecutionPlan, graph):
    return asyncio.run(AnswerSynthesizer(llm_enabled=False).synthesize(plan, graph))


def _registry():
    return build_default_tool_registry(
        Settings(stratz_graphql_url="https://api.stratz.test/graphql", stratz_token="token")
    )


class FakeLLM:
    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        return "Grounded answer."

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> dict[str, Any]:
        return {
            "summary": "Grounded answer.",
            "claims": [],
            "recommendations": [],
            "limitations": [],
            "confidence": 0.7,
        }

    async def complete_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 1000,
    ) -> ToolCallResult | None:
        return None


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
