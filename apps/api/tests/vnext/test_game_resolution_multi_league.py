from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import pytest

from app.vnext.providers.match_resolution import (
    CandidateAssessment,
    LeagueScopedCandidateAssessment,
    resolve_game_across_leagues,
)
from app.vnext.providers.match_resolution.resolver import _merge_league_assessments

_START = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _epoch(offset: int = 0) -> int:
    return int(_START.timestamp()) + offset


def _context(
    *games: dict[str, Any],
    match_id: int = 1000,
    radiant_name: str = "Alpha",
    dire_name: str = "Beta",
    radiant_id: int = 10,
    dire_id: int = 20,
) -> dict[str, Any]:
    return {
        "id": match_id,
        "opponents": [
            {"opponent": {"id": radiant_id, "name": radiant_name}},
            {"opponent": {"id": dire_id, "name": dire_name}},
        ],
        "games": list(games),
    }


def _game(
    position: int = 1,
    *,
    game_id: int = 2000,
    begin_at: str = "2026-10-01T12:00:00Z",
    length: int = 1907,
    winner_id: int = 10,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": game_id,
        "position": position,
        "begin_at": begin_at,
        "length": length,
        "winner": {"id": winner_id, "type": "Team"},
        "winner_id": winner_id,
        "winner_type": "Team",
        **extra,
    }


def _row(match_id: int, *, offset: int = 0, duration: int = 1907, **extra: Any):
    return {
        "match_id": match_id,
        "start_time": _epoch(offset),
        "duration": duration,
        **extra,
    }


def _detail(
    match_id: int,
    *,
    offset: int = 0,
    duration: int = 1907,
    radiant_name: str = "Alpha",
    dire_name: str = "Beta",
    radiant_win: bool = True,
    **extra: Any,
):
    return {
        "match_id": match_id,
        "start_time": _epoch(offset),
        "duration": duration,
        "radiant_team": {"team_id": 800, "name": radiant_name},
        "dire_team": {"team_id": 900, "name": dire_name},
        "radiant_win": radiant_win,
        **extra,
    }


def _resolve(
    context: dict[str, Any],
    league_ids: list[int],
    lists: dict[int, list[dict[str, Any]]],
    details: dict[int, dict[str, Any]],
    *,
    mappings: dict[int, int] | None = None,
    start_tolerance: int = 60,
    duration_tolerance: int = 10,
):
    return resolve_game_across_leagues(
        context,  # type: ignore[arg-type]
        1,
        league_ids,  # type: ignore[arg-type]
        lists,  # type: ignore[arg-type]
        details,  # type: ignore[arg-type]
        start_time_tolerance_seconds=start_tolerance,
        duration_tolerance_seconds=duration_tolerance,
        confirmed_mappings=mappings or {},
    )


def test_one_accepted_candidate_and_an_explicitly_empty_scope_resolve() -> None:
    valve_id = 9040000001
    result = _resolve(
        _context(_game()),
        [101, 202],
        {101: [_row(valve_id)], 202: []},
        {valve_id: _detail(valve_id)},
    )

    assert result.category == "resolved"
    assert result.valve_game_id == valve_id
    assert result.searched_league_ids == (101, 202)
    assert result.missing_league_ids == ()
    diagnostics = [
        (item.league_id, item.unusable_record_count)
        for item in result.league_search_diagnostics
    ]
    assert diagnostics == [
        (101, 0),
        (202, 0),
    ]


def test_distinct_accepted_valve_ids_across_leagues_are_ambiguous() -> None:
    first, second = 9040000001, 9040000002
    result = _resolve(
        _context(_game()),
        [101, 202],
        {101: [_row(first)], 202: [_row(second, offset=10)]},
        {
            first: _detail(first),
            second: _detail(second, offset=10),
        },
    )

    assert result.category == "ambiguous"
    assert result.valve_game_id is None
    assert [item.candidate_valve_game_id for item in result.candidate_assessments] == [
        first,
        second,
    ]
    assert all(item.status == "accepted" for item in result.candidate_assessments)


def test_accepted_candidate_with_missing_detail_competitor_is_insufficient() -> None:
    accepted_id, missing_detail_id = 9040000001, 9040000002
    result = _resolve(
        _context(_game()),
        [101, 202],
        {101: [_row(accepted_id)], 202: [_row(missing_detail_id, offset=10)]},
        {accepted_id: _detail(accepted_id)},
    )

    assert result.category == "evidence_insufficient"
    assert result.valve_game_id is None
    assert [item.status for item in result.candidate_assessments] == [
        "accepted",
        "unresolved",
    ]
    assert result.candidate_assessments[1].reasons == ("candidate_detail_missing",)


def test_accepted_candidate_and_explicitly_excluded_competitor_resolve() -> None:
    accepted_id, excluded_id = 9040000001, 9040000002
    result = _resolve(
        _context(_game()),
        [101, 202],
        {101: [_row(accepted_id)], 202: [_row(excluded_id, offset=15)]},
        {
            accepted_id: _detail(accepted_id),
            excluded_id: _detail(excluded_id, offset=61),
        },
    )

    assert result.category == "resolved"
    assert result.valve_game_id == accepted_id
    assert [item.status for item in result.candidate_assessments] == [
        "accepted",
        "excluded",
    ]
    assert result.candidate_assessments[1].reasons == (
        "detail_start_outside_tolerance",
    )


def test_same_valve_id_accepted_in_multiple_leagues_is_one_global_candidate() -> None:
    valve_id = 9040000001
    row = _row(valve_id)
    result = _resolve(
        _context(_game()),
        [101, 202],
        {101: [row], 202: [row]},
        {valve_id: _detail(valve_id)},
    )

    assert result.category == "resolved"
    assert result.valve_game_id == valve_id
    assert len(result.candidate_assessments) == 1
    grouped = result.candidate_assessments[0]
    assert grouped.status == "accepted"
    assert [item.league_id for item in grouped.league_assessments] == [101, 202]


def test_same_valve_id_excluded_in_all_leagues_is_one_excluded_candidate() -> None:
    valve_id = 9040000001
    row = _row(valve_id)
    detail = _detail(valve_id, offset=61)
    result = _resolve(
        _context(_game()),
        [101, 202],
        {101: [row], 202: [row]},
        {valve_id: detail},
    )

    assert result.category == "no_acceptable_candidate"
    assert len(result.candidate_assessments) == 1
    grouped = result.candidate_assessments[0]
    assert grouped.status == "excluded"
    assert [item.assessment.status for item in grouped.league_assessments] == [
        "excluded",
        "excluded",
    ]


def test_same_valve_id_source_assessment_conflict_remains_unresolved() -> None:
    accepted = CandidateAssessment(
        candidate_valve_game_id=9040000001,
        list_start_deltas_seconds=(0,),
        list_duration_deltas_seconds=(0,),
        detail_start_delta_seconds=0,
        detail_duration_delta_seconds=0,
        status="accepted",
        identity_evidence=None,
        reasons=(),
    )
    excluded = CandidateAssessment(
        candidate_valve_game_id=9040000001,
        list_start_deltas_seconds=(0,),
        list_duration_deltas_seconds=(0,),
        detail_start_delta_seconds=61,
        detail_duration_delta_seconds=0,
        status="excluded",
        identity_evidence=None,
        reasons=("detail_start_outside_tolerance",),
    )

    merged = _merge_league_assessments(
        9040000001,
        [
            LeagueScopedCandidateAssessment(101, accepted),
            LeagueScopedCandidateAssessment(202, excluded),
        ],
    )

    assert merged.status == "unresolved"
    assert "cross_league_assessment_conflict" in merged.reasons
    assert [item.league_id for item in merged.league_assessments] == [101, 202]


def test_same_valve_id_unresolved_assessment_keeps_merged_group_unresolved() -> None:
    excluded = CandidateAssessment(
        candidate_valve_game_id=9040000001,
        list_start_deltas_seconds=(0,),
        list_duration_deltas_seconds=(0,),
        detail_start_delta_seconds=61,
        detail_duration_delta_seconds=0,
        status="excluded",
        identity_evidence=None,
        reasons=("detail_start_outside_tolerance",),
    )
    unresolved = CandidateAssessment(
        candidate_valve_game_id=9040000001,
        list_start_deltas_seconds=(0,),
        list_duration_deltas_seconds=(0,),
        detail_start_delta_seconds=None,
        detail_duration_delta_seconds=0,
        status="unresolved",
        identity_evidence=None,
        reasons=("detail_start_time_unusable",),
    )

    merged = _merge_league_assessments(
        9040000001,
        [
            LeagueScopedCandidateAssessment(101, excluded),
            LeagueScopedCandidateAssessment(202, unresolved),
        ],
    )

    assert merged.status == "unresolved"
    assert merged.reasons == (
        "detail_start_outside_tolerance",
        "detail_start_time_unusable",
    )


def test_missing_scope_is_not_treated_as_an_empty_list() -> None:
    valve_id = 9040000001
    missing = _resolve(
        _context(_game()),
        [101, 202],
        {101: [_row(valve_id)]},
        {valve_id: _detail(valve_id)},
    )
    explicitly_empty = _resolve(_context(_game()), [101], {101: []}, {})

    assert missing.category == "search_scope_incomplete"
    assert missing.reason == "selected_league_list_missing"
    assert missing.missing_league_ids == (202,)
    assert missing.valve_game_id is None
    assert missing.candidate_assessments[0].status == "accepted"
    assert missing.league_search_diagnostics[1].unusable_record_count is None
    assert explicitly_empty.category == "no_candidates"
    assert explicitly_empty.missing_league_ids == ()


def test_empty_league_selection_has_specific_no_candidate_reason() -> None:
    result = _resolve(_context(_game()), [], {}, {})

    assert result.category == "no_candidates"
    assert result.reason == "no_league_candidates"
    assert result.searched_league_ids == ()


def test_no_candidates_excluded_candidates_and_unresolved_candidates_differ() -> None:
    no_candidates = _resolve(_context(_game()), [101], {101: []}, {})
    excluded_id = 9040000001
    excluded = _resolve(
        _context(_game()),
        [101],
        {101: [_row(excluded_id)]},
        {excluded_id: _detail(excluded_id, offset=61)},
    )
    unresolved_id = 9040000002
    unresolved = _resolve(
        _context(_game()),
        [101],
        {101: [_row(unresolved_id)]},
        {},
    )

    assert no_candidates.category == "no_candidates"
    assert excluded.category == "no_acceptable_candidate"
    assert unresolved.category == "evidence_insufficient"


@pytest.mark.parametrize(
    ("mappings", "reason"),
    [
        ({3000: 9040000001}, "valve_game_already_assigned"),
        ({2000: 9040000002}, "pandascore_game_already_mapped"),
    ],
)
def test_global_unique_candidate_still_obeys_confirmed_mapping_rules(
    mappings: dict[int, int], reason: str
) -> None:
    valve_id = 9040000001
    result = _resolve(
        _context(_game()),
        [101, 202],
        {101: [_row(valve_id)], 202: []},
        {valve_id: _detail(valve_id)},
        mappings=mappings,
    )

    assert result.category == "mapping_conflict"
    assert result.reason == reason
    assert result.valve_game_id is None


def test_league_and_record_order_do_not_change_global_resolution() -> None:
    accepted_id, excluded_id = 9040000001, 9040000002
    context = _context(_game())
    details = {
        accepted_id: _detail(accepted_id),
        excluded_id: _detail(excluded_id, offset=61),
    }
    forward = _resolve(
        context,
        [101, 202],
        {101: [_row(accepted_id)], 202: [_row(excluded_id, offset=10)]},
        details,
    )
    reverse = _resolve(
        context,
        [202, 101],
        {
            202: [_row(excluded_id, offset=10)],
            101: [_row(accepted_id)],
        },
        details,
    )

    assert (forward.category, forward.valve_game_id) == (
        reverse.category,
        reverse.valve_game_id,
    ) == ("resolved", accepted_id)


def test_duplicate_league_ids_are_deduplicated_and_inputs_are_unchanged() -> None:
    valve_id = 9040000001
    context = _context(_game())
    rows = {101: [_row(valve_id)]}
    details = {valve_id: _detail(valve_id)}
    mappings = {3000: 9040000003}
    before = deepcopy((context, rows, details, mappings))

    result = _resolve(
        context,
        [101, 101],
        rows,
        details,
        mappings=mappings,
    )

    assert result.category == "resolved"
    assert result.searched_league_ids == (101,)
    assert (context, rows, details, mappings) == before


@pytest.mark.parametrize("league_ids", [[True], [0], [-1], [1.0], ["1"]])
def test_invalid_league_ids_are_rejected(league_ids: list[Any]) -> None:
    with pytest.raises(ValueError, match="positive integers"):
        _resolve(_context(_game()), league_ids, {}, {})  # type: ignore[arg-type]


def test_blast_game_four_resolves_with_verified_historical_fields() -> None:
    match_id, game_id, valve_id = 1709131, 739826, 9040578015
    context = _context(
        _game(
            4,
            game_id=game_id,
            begin_at="2026-10-11T18:33:41Z",
            length=3400,
            winner_id=137073,
        ),
        match_id=match_id,
        radiant_id=137073,
        radiant_name="Team Yandex",
        dire_id=1669,
        dire_name="Team Spirit",
    )
    row = {
        "match_id": valve_id,
        "start_time": 1791743534,
        "duration": 3400,
        "series_id": 1153562,
        "leagueid": 19102,
    }
    detail = {
        "match_id": valve_id,
        "start_time": 1791743534,
        "duration": 3400,
        "radiant_team": {"team_id": 9823272, "name": "Team Yandex"},
        "dire_team": {"team_id": 7119388, "name": "Team Spirit"},
        "radiant_win": True,
    }

    result = resolve_game_across_leagues(
        context,  # type: ignore[arg-type]
        4,
        [19102],
        {19102: [row]},
        {valve_id: detail},
        start_time_tolerance_seconds=180,
        duration_tolerance_seconds=5,
        confirmed_mappings={},
    )

    assert result.category == "resolved"
    assert result.pandascore_match_id == match_id
    assert result.pandascore_game_id == game_id
    assert result.searched_league_ids == (19102,)
    assert result.valve_game_id == valve_id
    list_start_deltas = (
        result.candidate_assessments[0]
        .league_assessments[0]
        .assessment.list_start_deltas_seconds
    )
    assert list_start_deltas == (
        -87,
    )
