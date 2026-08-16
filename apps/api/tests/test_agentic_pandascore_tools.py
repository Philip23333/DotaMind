from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.agentic.models import ExecutionPlan, ToolCall, ToolResult
from app.agentic.planning.contracts import validate_references, validate_required_references
from app.agentic.tools.pandascore_tools import (
    PandaScoreResolveCompetitionInput,
    _competition_match_rank,
    _extract_explicit_year,
    _resolve_competition_handler,
    competition_evidence,
    match_game_evidence,
    match_schedule_evidence,
    select_latest_competition,
)
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings
from app.integrations.pandascore.models import PandaCompetition


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


def _competition(series_id: int, year: int, begin: str, end: str | None) -> PandaCompetition:
    return PandaCompetition(
        pandascore_series_id=series_id,
        name="The International",
        full_name=str(year),
        year=year,
        league={"id": 4106, "name": "The International"},
        tournaments=[{"begin_at": begin, "end_at": end}],
    )


def test_competition_year_parsing_and_conflict_are_deterministic() -> None:
    assert _extract_explicit_year("The International 2025") == ("The International", 2025)
    assert _extract_explicit_year("2025 The International") == ("The International", 2025)
    assert _extract_explicit_year("The International") == ("The International", None)
    with pytest.raises(ValueError, match="year conflicts"):
        PandaScoreResolveCompetitionInput(query="The International 2025", year=2026)


def test_latest_competition_prefers_active_and_ignores_input_order() -> None:
    now = datetime(2026, 8, 16, tzinfo=UTC)
    current = _competition(10828, 2026, "2026-08-13T00:00:00Z", "2026-08-23T00:00:00Z")
    previous = _competition(10000, 2025, "2025-09-01T00:00:00Z", "2025-09-30T00:00:00Z")
    selection = select_latest_competition([previous, current], now=now, match_rank=3)
    assert selection.status == "resolved"
    assert selection.selected is not None
    assert selection.selected.pandascore_series_id == 10828
    assert selection.selected_year == 2026
    assert selection.candidate_count_before_selection == 2


def test_competition_match_rank_prefers_series_name_over_parent_league() -> None:
    main = _competition(10828, 2026, "2026-08-13T00:00:00Z", "2026-08-23T00:00:00Z")
    qualifier = main.model_copy(
        update={"pandascore_series_id": 10829, "name": "Western Europe Qualifier"}
    )
    assert _competition_match_rank(main, "The International") == 3
    assert _competition_match_rank(qualifier, "The International") == 2


def test_explicit_year_does_not_fall_back_to_latest() -> None:
    current = _competition(10828, 2026, "2026-08-13T00:00:00Z", "2026-08-23T00:00:00Z")
    selection = select_latest_competition(
        [row for row in [current] if row.year == 2025],
        now=datetime(2026, 8, 16, tzinfo=UTC),
        requested_year=2025,
        match_rank=3,
    )
    assert selection.status == "not_found"


def test_latest_selection_uses_recent_history_when_no_active_candidate() -> None:
    now = datetime(2026, 8, 16, tzinfo=UTC)
    older = _competition(10000, 2024, "2024-09-01T00:00:00Z", "2024-09-30T00:00:00Z")
    recent = _competition(10001, 2025, "2025-09-01T00:00:00Z", "2025-09-30T00:00:00Z")
    selection = select_latest_competition([recent, older], now=now)
    assert selection.status == "resolved"
    assert selection.selected_year == 2025


def test_latest_selection_uses_nearest_future_candidate() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    later = _competition(10001, 2027, "2027-09-01T00:00:00Z", "2027-09-30T00:00:00Z")
    sooner = _competition(10000, 2026, "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z")
    selection = select_latest_competition([later, sooner], now=now)
    assert selection.status == "resolved"
    assert selection.selected_year == 2026


def test_latest_selection_returns_ambiguous_for_equal_temporal_candidates() -> None:
    now = datetime(2026, 8, 16, tzinfo=UTC)
    first = _competition(10000, 2026, "2026-08-13T00:00:00Z", "2026-08-23T00:00:00Z")
    second = _competition(10001, 2026, "2026-08-13T00:00:00Z", "2026-08-23T00:00:00Z")
    selection = select_latest_competition([first, second], now=now)
    assert selection.status == "ambiguous"
    assert selection.selected is None


@pytest.mark.anyio
async def test_resolver_pushes_explicit_year_before_name_ranking(monkeypatch) -> None:
    rows = [
        _competition(9555, 2025, "2025-08-01T00:00:00Z", "2025-09-01T00:00:00Z"),
        _competition(10828, 2026, "2026-08-13T00:00:00Z", "2026-08-23T00:00:00Z"),
    ]

    class FakeTransport:
        async def aclose(self) -> None:
            return None

    class FakeCompetitions:
        def __init__(self) -> None:
            self.requested_year = "unset"

        async def list_series(self, *, year=None):
            self.requested_year = year
            return rows

    transport = FakeTransport()
    competitions = FakeCompetitions()
    monkeypatch.setattr(
        "app.agentic.tools.pandascore_tools._clients",
        lambda _settings, _policy: (transport, competitions, object()),
    )
    handler = _resolve_competition_handler(Settings(_env_file=None), object())
    result = await handler(PandaScoreResolveCompetitionInput(query="The International 2025"), None)

    assert competitions.requested_year == 2025
    assert result["status"] == "resolved"
    assert result["competition"]["series_id"] == 9555
