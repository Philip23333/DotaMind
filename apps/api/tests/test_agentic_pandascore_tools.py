from __future__ import annotations

from app.agentic.models import ExecutionPlan, ToolCall, ToolResult
from app.agentic.planning.contracts import validate_references, validate_required_references
from app.agentic.tools.pandascore_tools import (
    competition_evidence,
    match_game_evidence,
    match_schedule_evidence,
)
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings


def test_registry_declares_three_pandascore_tools_and_contracts() -> None:
    registry = build_default_tool_registry(Settings(_env_file=None))
    resolve = registry.get("pandascore.resolve_competition")
    listing = registry.get("pandascore.list_matches")
    resolver = registry.get("pandascore.resolve_match_game")
    assert resolve.output_paths["series_id"].path == "data.competition.series_id"
    assert listing.arg_contracts["series_id"].requires_reference is True
    assert resolver.arg_contracts["series_id"].requires_reference is True
    assert resolver.mandatory_evidence == ("match_identity", "pandascore_game_identity")


def test_ambiguous_and_malformed_results_do_not_create_identity_evidence() -> None:
    result = ToolResult(
        tool_call_id="c1",
        tool="pandascore.resolve_competition",
        status="ok",
        data={"status": "ambiguous", "candidates": []},
        latency_ms=1,
    )
    assert competition_evidence(result) == []
    malformed = result.model_copy(update={"data": {"status": "resolved", "competition": {}}})
    assert competition_evidence(malformed) == []


def test_schedule_and_match_evidence_are_scoped_to_call() -> None:
    fixture = {
        "pandascore_match_id": 1631694,
        "name": "NGX vs OG",
        "status": "finished",
        "scheduled_at": "2026-08-13T09:30:00Z",
        "results": [{"score": 2, "team_id": 129609}],
    }
    result = ToolResult(
        tool_call_id="c2",
        tool="pandascore.list_matches",
        status="ok",
        data={"matches": [fixture]},
        latency_ms=1,
    )
    evidence = match_schedule_evidence(result)
    assert {item.kind for item in evidence} == {"match_schedule", "match_state", "series_score"}
    assert all(item.tool_call_id == "c2" for item in evidence)

    pending = ToolResult(
        tool_call_id="c3",
        tool="pandascore.resolve_match_game",
        status="ok",
        data={
            "status": "pending_valve_match_id",
            "match": {"pandascore_match_id": 1631694, "pandascore_series_id": 10828},
            "game": {"pandascore_game_id": 738652, "valve_match_id": None},
        },
        latency_ms=1,
    )
    assert {item.kind for item in match_game_evidence(pending)} == {
        "match_identity",
        "pandascore_game_identity",
        "series_context",
    }


def test_reference_contracts_reject_literals_and_accept_declared_paths() -> None:
    registry = build_default_tool_registry(Settings(_env_file=None))
    literal_plan = ExecutionPlan(
        intent="schedule",
        goal="list",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="c1", tool="pandascore.list_matches", args={"series_id": 10828})
        ],
    )
    assert validate_required_references(literal_plan, registry)

    valid_plan = ExecutionPlan(
        intent="schedule",
        goal="list",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(
                id="c1",
                tool="pandascore.resolve_competition",
                args={"query": "The International 2026"},
            ),
            ToolCall(
                id="c2",
                tool="pandascore.list_matches",
                args={"series_id": "$c1.data.competition.series_id"},
            ),
        ],
    )
    assert validate_required_references(valid_plan, registry) == []
    assert validate_references(valid_plan, registry) == []

    draft_literal = ExecutionPlan(
        intent="draft",
        goal="draft",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="d1", tool="opendota.match_draft", args={"valve_match_id": 8943244303})
        ],
    )
    assert validate_required_references(draft_literal, registry)
