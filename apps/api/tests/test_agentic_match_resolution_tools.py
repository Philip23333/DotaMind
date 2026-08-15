from __future__ import annotations

from app.agentic.models import ExecutionPlan, ToolCall, ToolResult
from app.agentic.planning.contracts import validate_references, validate_required_references
from app.agentic.tools.match_resolution_tools import valve_match_evidence
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings


def test_resolver_tool_contract_and_declared_refs() -> None:
    registry = build_default_tool_registry(Settings(_env_file=None))
    tool = registry.get("dota.resolve_valve_match")
    assert tool.source.kind == "cross_source_inference"
    assert tool.mandatory_evidence == (
        "cross_source_match_mapping",
        "valve_match_identity",
    )
    assert tool.arg_contracts["competition"].requires_reference is True
    assert tool.arg_contracts["game_context"].requires_reference is True
    assert tool.output_paths["valve_match_id"].path == "data.match.valve_match_id"

    plan = ExecutionPlan(
        intent="match",
        goal="resolve one game",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(
                id="competition",
                tool="pandascore.resolve_competition",
                args={"query": "The International 2026"},
            ),
            ToolCall(
                id="game",
                tool="pandascore.resolve_match_game",
                args={
                    "series_id": "$competition.data.competition.series_id",
                    "team_queries": ["Nigma Galaxy", "OG"],
                    "game_number": 1,
                },
            ),
            ToolCall(
                id="mapping",
                tool="dota.resolve_valve_match",
                args={
                    "competition": "$competition.data.competition",
                    "game_context": "$game.data.resolution_input",
                },
            ),
            ToolCall(
                id="summary",
                tool="opendota.match_summary",
                args={"valve_match_id": "$mapping.data.match.valve_match_id"},
            ),
            ToolCall(
                id="draft",
                tool="opendota.match_draft",
                args={"valve_match_id": "$summary.data.match.match_id"},
            ),
        ],
    )
    assert validate_required_references(plan, registry) == []
    assert validate_references(plan, registry) == []


def test_resolver_evidence_requires_resolved_complete_mapping() -> None:
    base = ToolResult(
        tool_call_id="r1",
        tool="dota.resolve_valve_match",
        status="ok",
        data={"status": "ambiguous_team"},
        latency_ms=1,
    )
    assert valve_match_evidence(base) == []

    resolved = base.model_copy(
        update={
            "data": {
                "status": "resolved",
                "match": {
                    "valve_match_id": 8943244303,
                    "opendota_league_id": 19719,
                    "opendota_series_id": 1130066,
                },
                "mapping": {
                    "method": "inferred_cross_source",
                    "pandascore_game_id": 738652,
                },
            }
        }
    )
    assert {item.kind for item in valve_match_evidence(resolved)} == {
        "cross_source_match_mapping",
        "valve_match_identity",
    }
