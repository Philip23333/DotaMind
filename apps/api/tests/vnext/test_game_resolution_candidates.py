from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.vnext.providers.match_resolution import find_game_candidates

_BASE_START = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
_LEAGUE_ID = 20359


def _epoch(offset_seconds: int = 0) -> int:
    return int((_BASE_START + timedelta(seconds=offset_seconds)).timestamp())


def _context(
    *games: dict[str, object],
    include_games: bool = True,
) -> dict[str, object]:
    context: dict[str, object] = {"id": 1709131}
    if include_games:
        context["games"] = list(games)
    return context


def _game(
    position: int = 1,
    *,
    begin_at: object = "2026-10-01T12:00:00Z",
    length: object = 1907,
    **extra: object,
) -> dict[str, object]:
    return {
        "id": 739823 + position - 1,
        "position": position,
        "begin_at": begin_at,
        "length": length,
        **extra,
    }


def _opendota(
    match_id: int,
    *,
    start_offset: int = 0,
    duration: int = 1907,
    **extra: object,
) -> dict[str, object]:
    return {
        "match_id": match_id,
        "start_time": _epoch(start_offset),
        "duration": duration,
        **extra,
    }


def _find(
    context: dict[str, object],
    rows: list[dict[str, object]],
    *,
    position: int = 1,
    league_id: int = _LEAGUE_ID,
    start_tolerance: int = 60,
    duration_tolerance: int = 10,
):
    return find_game_candidates(
        context,  # type: ignore[arg-type]
        position,
        league_id,
        rows,  # type: ignore[arg-type]
        start_time_tolerance_seconds=start_tolerance,
        duration_tolerance_seconds=duration_tolerance,
    )


def test_one_candidate_preserves_record_and_signed_deltas_without_resolving() -> None:
    source = _opendota(
        9040000001,
        start_offset=-12,
        duration=1910,
        series_id=0,
        custom_provider_field={"kept": True},
    )

    result = _find(_context(_game()), [source])

    assert result.category == "candidates_found"
    assert result.searched_league_id == _LEAGUE_ID
    assert result.target_game == _game()
    assert len(result.candidates) == 1
    assert result.candidates[0].record is source
    assert result.candidates[0].start_delta_seconds == -12
    assert result.candidates[0].duration_delta_seconds == 3
    assert result.unusable_record_count == 0
    assert result.reason is None
    assert not hasattr(result, "resolved")
    assert not hasattr(result, "valve_game_id")


def test_multiple_candidates_keep_all_rows_in_source_order_not_closest_first() -> None:
    farther = _opendota(9040000001, start_offset=20)
    nearer = _opendota(9040000002, start_offset=1)

    result = _find(_context(_game()), [farther, nearer])

    assert result.category == "candidates_found"
    assert [candidate.record["match_id"] for candidate in result.candidates] == [
        9040000001,
        9040000002,
    ]
    assert [candidate.start_delta_seconds for candidate in result.candidates] == [
        20,
        1,
    ]


def test_no_candidates_reports_only_current_scope_and_tolerances() -> None:
    result = _find(_context(_game()), [_opendota(9040000001, start_offset=61)])

    assert result.category == "no_candidates"
    assert result.searched_league_id == _LEAGUE_ID
    assert result.candidates == ()
    assert result.reason == "no_candidate_within_tolerances"


def test_tolerance_boundaries_are_inclusive_and_both_signals_must_fit() -> None:
    at_both_boundaries = _opendota(
        9040000001,
        start_offset=-10,
        duration=1912,
    )
    outside_time = _opendota(9040000002, start_offset=11)
    outside_duration = _opendota(9040000003, duration=1913)

    result = _find(
        _context(_game()),
        [at_both_boundaries, outside_time, outside_duration],
        start_tolerance=10,
        duration_tolerance=5,
    )

    assert result.category == "candidates_found"
    assert [candidate.record["match_id"] for candidate in result.candidates] == [
        9040000001
    ]
    assert result.candidates[0].start_delta_seconds == -10
    assert result.candidates[0].duration_delta_seconds == 5


def test_target_game_is_selected_by_position_not_array_order() -> None:
    first = _game(1, begin_at="2026-10-01T12:00:00Z")
    second = _game(2, begin_at="2026-10-01T13:00:00Z")
    second_start = int(datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc).timestamp())
    source = {"match_id": 9040000002, "start_time": second_start, "duration": 1907}

    result = _find(
        _context(second, first),
        [source],
        position=2,
    )

    assert result.category == "candidates_found"
    assert result.target_game == second
    assert result.candidates[0].record is source


def test_duplicate_target_position_is_ambiguous_without_selecting_first() -> None:
    result = _find(_context(_game(1), _game(1, id=999999)), [])

    assert result.category == "ambiguous_target_game"
    assert result.target_game is None
    assert result.candidates == ()
    assert result.reason == "duplicate_game_position"


@pytest.mark.parametrize(
    ("context", "reason"),
    [
        (_context(include_games=False), "games_missing"),
        ({"games": None}, "games_null"),
        (_context(), "games_empty"),
        ({"games": "invalid"}, "games_invalid"),
        (_context(_game(2)), "position_not_found"),
    ],
)
def test_missing_game_collection_or_position_has_specific_reason(
    context: dict[str, object],
    reason: str,
) -> None:
    result = _find(context, [])

    assert result.category == "target_game_not_found"
    assert result.target_game is None
    assert result.reason == reason


@pytest.mark.parametrize(
    ("game", "reason"),
    [
        (_game(forfeit=True), "target_game_forfeit"),
        (_game(status="not_started"), "target_game_not_started"),
    ],
)
def test_forfeited_or_not_started_target_is_not_candidate_searched(
    game: dict[str, object],
    reason: str,
) -> None:
    result = _find(_context(game), [_opendota(9040000001)])

    assert result.category == "target_not_ready"
    assert result.target_game is game
    assert result.candidates == ()
    assert result.reason == reason


@pytest.mark.parametrize(
    ("game", "reason"),
    [
        (_game(begin_at=None), "begin_at_empty"),
        (_game(begin_at=""), "begin_at_empty"),
        (_game(begin_at="not-a-date"), "begin_at_invalid"),
        (_game(begin_at="2026-10-01T12:00:00"), "begin_at_timezone_missing"),
        (_game(begin_at=123), "begin_at_invalid"),
        (_game(length=None), "length_empty"),
        (_game(length=""), "length_empty"),
        (_game(length=True), "length_invalid"),
        (_game(length="1907"), "length_invalid"),
        (_game(length=-1), "length_invalid"),
    ],
)
def test_missing_or_unusable_target_signals_return_insufficient_signals(
    game: dict[str, object],
    reason: str,
) -> None:
    result = _find(_context(game), [_opendota(9040000001)])

    assert result.category == "insufficient_signals"
    assert result.target_game is game
    assert result.candidates == ()
    assert result.reason == reason


def test_absent_or_changed_team_and_series_ids_do_not_filter_candidates() -> None:
    rows = [
        _opendota(9040000001, series_id=None),
        _opendota(9040000002, series_id=0, radiant_team_id=10, dire_team_id=20),
        _opendota(9040000003, series_id=1153562, radiant_team_id=30),
    ]

    result = _find(_context(_game()), rows)

    assert result.category == "candidates_found"
    assert [candidate.record["match_id"] for candidate in result.candidates] == [
        9040000001,
        9040000002,
        9040000003,
    ]


def test_unusable_opendota_rows_are_counted_not_misclassified_as_mismatches() -> None:
    valid = {"match_id": 9040000001, "start_time": _epoch(), "duration": 1907}
    rows = [
        {"match_id": 1, "duration": 1907},
        {"match_id": 2, "start_time": _epoch()},
        {"match_id": 3, "start_time": None, "duration": 1907},
        {"match_id": 4, "start_time": _epoch(), "duration": True},
        {"match_id": 5, "start_time": _epoch(), "duration": -1},
        valid,
    ]

    result = _find(_context(_game()), rows)

    assert result.category == "candidates_found"
    assert result.unusable_record_count == 5
    assert len(result.candidates) == 1
    assert result.candidates[0].record is valid


def test_blast_final_game_candidate_ignores_different_opendota_series_id() -> None:
    target = _game(4, begin_at="2026-10-11T18:33:41Z", length=3400)
    blast_candidate = {
        "match_id": 9040578015,
        "start_time": 1791743534,
        "duration": 3400,
        "series_id": 1153562,
        "leagueid": 19102,
    }
    context = _context(target)
    context["id"] = 1709131
    context["serie"] = {"id": 11012}

    result = _find(
        context,
        [blast_candidate],
        position=4,
        league_id=19102,
        start_tolerance=180,
        duration_tolerance=5,
    )

    assert result.category == "candidates_found"
    assert result.target_game is target
    assert result.target_game["id"] == 739826
    assert result.searched_league_id == 19102
    assert result.candidates[0].record["match_id"] == 9040578015
    assert result.candidates[0].start_delta_seconds == -87
    assert result.candidates[0].duration_delta_seconds == 0


def test_south_america_game_stays_outside_initial_window_without_absence_claim() -> None:
    target = _game(
        3,
        begin_at="2026-10-13T02:31:22Z",
        length=1907,
    )
    od_start = int(
        datetime(2026, 10, 13, 2, 31, 22, tzinfo=timezone.utc).timestamp()
    ) - 10258
    source = {"match_id": 9042461131, "start_time": od_start, "duration": 1907}

    result = _find(
        _context(target),
        [source],
        position=3,
        league_id=20359,
        start_tolerance=1800,
        duration_tolerance=5,
    )

    assert result.category == "no_candidates"
    assert result.searched_league_id == 20359
    assert result.candidates == ()
    assert result.reason == "no_candidate_within_tolerances"
    assert result.unusable_record_count == 0


def test_input_records_are_not_modified() -> None:
    context = _context(_game())
    rows = [_opendota(9040000001, custom={"nested": [1, 2]})]
    context_before = deepcopy(context)
    rows_before = deepcopy(rows)

    _find(context, rows)

    assert context == context_before
    assert rows == rows_before


@pytest.mark.parametrize(
    ("position", "league_id", "start_tolerance", "duration_tolerance"),
    [
        (0, _LEAGUE_ID, 0, 0),
        (True, _LEAGUE_ID, 0, 0),
        ("1", _LEAGUE_ID, 0, 0),
        (1.0, _LEAGUE_ID, 0, 0),
        (1, 0, 0, 0),
        (1, False, 0, 0),
        (1, "20359", 0, 0),
        (1, _LEAGUE_ID, -1, 0),
        (1, _LEAGUE_ID, True, 0),
        (1, _LEAGUE_ID, 0, -1),
        (1, _LEAGUE_ID, 0, 1.5),
    ],
)
def test_invalid_position_league_or_tolerance_is_rejected(
    position: object,
    league_id: object,
    start_tolerance: object,
    duration_tolerance: object,
) -> None:
    with pytest.raises(ValueError):
        find_game_candidates(
            _context(_game()),  # type: ignore[arg-type]
            position,  # type: ignore[arg-type]
            league_id,  # type: ignore[arg-type]
            [],
            start_time_tolerance_seconds=start_tolerance,  # type: ignore[arg-type]
            duration_tolerance_seconds=duration_tolerance,  # type: ignore[arg-type]
        )
