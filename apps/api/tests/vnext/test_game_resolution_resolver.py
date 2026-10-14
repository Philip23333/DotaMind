from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import pytest

from app.vnext.providers.match_resolution import resolve_game

_START = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
_LEAGUE_ID = 20359


def _epoch(offset: int = 0) -> int:
    return int((_START.timestamp()) + offset)


def _context(
    *games: dict[str, Any],
    match_id: int = 1000,
    radiant_id: int | None = 10,
    radiant_name: str = "Alpha",
    dire_id: int | None = 20,
    dire_name: str = "Beta",
) -> dict[str, Any]:
    radiant = {"name": radiant_name}
    dire = {"name": dire_name}
    if radiant_id is not None:
        radiant["id"] = radiant_id
    if dire_id is not None:
        dire["id"] = dire_id
    return {
        "id": match_id,
        "opponents": [{"opponent": radiant}, {"opponent": dire}],
        "games": list(games),
    }


def _game(
    position: int = 1,
    *,
    game_id: int = 2000,
    begin_at: str = "2026-10-01T12:00:00Z",
    length: int = 1907,
    winner_id: int | None = 10,
    **extra: Any,
) -> dict[str, Any]:
    game: dict[str, Any] = {
        "id": game_id,
        "position": position,
        "begin_at": begin_at,
        "length": length,
        **extra,
    }
    if winner_id is not None:
        game["winner"] = {"id": winner_id, "type": "Team"}
        game["winner_id"] = winner_id
        game["winner_type"] = "Team"
    return game


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
    radiant_id: int | None = 800,
    radiant_name: str = "Alpha",
    dire_id: int | None = 900,
    dire_name: str | None = "Beta",
    radiant_win: bool | None = True,
    **extra: Any,
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "match_id": match_id,
        "start_time": _epoch(offset),
        "duration": duration,
    }
    if radiant_name is not None:
        radiant = {"name": radiant_name}
        if radiant_id is not None:
            radiant["team_id"] = radiant_id
        detail["radiant_team"] = radiant
    if dire_name is not None:
        dire = {"name": dire_name}
        if dire_id is not None:
            dire["team_id"] = dire_id
        detail["dire_team"] = dire
    if radiant_win is not None:
        detail["radiant_win"] = radiant_win
    detail.update(extra)
    return detail


def _resolve(
    context: dict[str, Any],
    rows: list[dict[str, Any]],
    details: dict[int, dict[str, Any]],
    *,
    position: int = 1,
    league_id: int = _LEAGUE_ID,
    start_tolerance: int = 60,
    duration_tolerance: int = 10,
    mappings: dict[int, int] | None = None,
):
    return resolve_game(
        context,  # type: ignore[arg-type]
        position,
        league_id,
        rows,  # type: ignore[arg-type]
        details,  # type: ignore[arg-type]
        start_time_tolerance_seconds=start_tolerance,
        duration_tolerance_seconds=duration_tolerance,
        confirmed_mappings=mappings or {},
    )


def test_unique_candidate_with_supported_participants_and_winner_resolves() -> None:
    candidate_id = 9040000001
    source = _row(candidate_id, offset=-12, duration=1910, series_id=0)
    detail = _detail(candidate_id, offset=-12, duration=1910)

    result = _resolve(_context(_game()), [source], {candidate_id: detail})

    assert result.category == "resolved"
    assert result.pandascore_match_id == 1000
    assert result.pandascore_game_id == 2000
    assert result.game_position == 1
    assert result.searched_league_id == _LEAGUE_ID
    assert result.valve_game_id == candidate_id
    assert result.method == "inferred_cross_source"
    assessment = result.candidate_assessments[0]
    assert assessment.status == "accepted"
    assert assessment.list_start_deltas_seconds == (-12,)
    assert assessment.list_duration_deltas_seconds == (3,)
    assert assessment.detail_start_delta_seconds == -12
    assert assessment.detail_duration_delta_seconds == 3
    assert assessment.identity_evidence is not None
    assert assessment.identity_evidence.participants_status == "supported"
    assert assessment.identity_evidence.winner_status == "consistent"


def test_time_and_duration_alone_do_not_confirm_identity() -> None:
    candidate_id = 9040000001
    context = _context(_game(), radiant_name="Alpha", dire_name="Beta")
    detail = _detail(
        candidate_id,
        radiant_name="Unknown Radiant",
        dire_name="Unknown Dire",
    )

    result = _resolve(context, [_row(candidate_id)], {candidate_id: detail})

    assert result.category == "evidence_insufficient"
    assert result.valve_game_id is None
    assert result.candidate_assessments[0].status == "unresolved"
    assert result.candidate_assessments[0].identity_evidence is not None


def test_unknown_winner_keeps_candidate_unresolved() -> None:
    candidate_id = 9040000001
    context = _context(_game(winner_id=None))

    result = _resolve(
        context,
        [_row(candidate_id)],
        {candidate_id: _detail(candidate_id)},
    )

    assert result.category == "evidence_insufficient"
    assert result.reason == "candidate_evidence_incomplete"
    assert result.valve_game_id is None
    assert result.candidate_assessments[0].identity_evidence.winner_status == "unknown"
    assert "game_winner_missing" in result.candidate_assessments[0].reasons


def test_explicit_winner_conflict_excludes_candidate() -> None:
    candidate_id = 9040000001

    result = _resolve(
        _context(_game()),
        [_row(candidate_id)],
        {candidate_id: _detail(candidate_id, radiant_win=False)},
    )

    assert result.category == "no_acceptable_candidate"
    assert result.valve_game_id is None
    assert result.candidate_assessments[0].status == "excluded"
    assert result.candidate_assessments[0].reasons == ("game_winner_conflict",)


def test_two_accepted_distinct_candidates_are_ambiguous() -> None:
    first_id, second_id = 9040000001, 9040000002
    rows = [_row(first_id, offset=-10), _row(second_id, offset=15)]
    details = {
        first_id: _detail(first_id, offset=-10),
        second_id: _detail(second_id, offset=15),
    }

    result = _resolve(_context(_game()), rows, details)

    assert result.category == "ambiguous"
    assert result.valve_game_id is None
    assert [item.candidate_valve_game_id for item in result.candidate_assessments] == [
        first_id,
        second_id,
    ]
    assert all(item.status == "accepted" for item in result.candidate_assessments)


def test_accepted_candidate_and_missing_competitor_detail_stays_unresolved() -> None:
    accepted_id, unknown_id = 9040000001, 9040000002

    result = _resolve(
        _context(_game()),
        [_row(accepted_id), _row(unknown_id, offset=20)],
        {accepted_id: _detail(accepted_id)},
    )

    assert result.category == "evidence_insufficient"
    assert result.reason == "unresolved_competing_candidate"
    assert result.valve_game_id is None
    assert [item.status for item in result.candidate_assessments] == [
        "accepted",
        "unresolved",
    ]
    assert result.candidate_assessments[1].reasons == ("candidate_detail_missing",)


def test_one_accepted_candidate_can_resolve_when_competitor_has_clear_conflict() -> None:
    accepted_id, excluded_id = 9040000001, 9040000002

    result = _resolve(
        _context(_game()),
        [_row(accepted_id), _row(excluded_id, offset=20)],
        {
            accepted_id: _detail(accepted_id),
            excluded_id: _detail(excluded_id, radiant_win=False),
        },
    )

    assert result.category == "resolved"
    assert result.valve_game_id == accepted_id
    assert [item.status for item in result.candidate_assessments] == [
        "accepted",
        "excluded",
    ]


def test_detail_outside_normal_window_excludes_list_candidate() -> None:
    candidate_id = 9040000001

    result = _resolve(
        _context(_game()),
        [_row(candidate_id, offset=10)],
        {candidate_id: _detail(candidate_id, offset=61)},
        start_tolerance=60,
    )

    assert result.category == "no_acceptable_candidate"
    assert result.valve_game_id is None
    assessment = result.candidate_assessments[0]
    assert assessment.status == "excluded"
    assert assessment.detail_start_delta_seconds == 61
    assert assessment.reasons == ("detail_start_outside_tolerance",)
    assert assessment.identity_evidence is None


def test_detail_timing_at_both_normal_window_boundaries_is_accepted() -> None:
    candidate_id = 9040000001

    result = _resolve(
        _context(_game()),
        [_row(candidate_id, offset=60, duration=1897)],
        {candidate_id: _detail(candidate_id, offset=-60, duration=1917)},
        start_tolerance=60,
        duration_tolerance=10,
    )

    assert result.category == "resolved"
    assert result.candidate_assessments[0].detail_start_delta_seconds == -60
    assert result.candidate_assessments[0].detail_duration_delta_seconds == 10


def test_missing_detail_timing_stays_unresolved_even_if_other_signal_is_outside() -> None:
    candidate_id = 9040000001
    detail = _detail(candidate_id, offset=61)
    detail.pop("duration")

    result = _resolve(
        _context(_game()),
        [_row(candidate_id)],
        {candidate_id: detail},
        start_tolerance=60,
    )

    assert result.category == "evidence_insufficient"
    assert result.candidate_assessments[0].status == "unresolved"
    assert result.candidate_assessments[0].reasons == (
        "detail_start_outside_tolerance",
        "detail_duration_unusable",
    )


def test_source_field_conflict_is_unresolved_not_an_exclusion() -> None:
    candidate_id = 9040000001
    conflicting_game = _game()
    conflicting_game["winner_id"] = 20

    result = _resolve(
        _context(conflicting_game),
        [_row(candidate_id)],
        {candidate_id: _detail(candidate_id)},
    )

    assert result.category == "evidence_insufficient"
    assert result.valve_game_id is None
    assessment = result.candidate_assessments[0]
    assert assessment.status == "unresolved"
    assert "game_winner_source_conflict" in assessment.reasons


@pytest.mark.parametrize(
    ("map_key", "detail_id"),
    [(9040000002, 9040000001), (9040000001, True), (9040000001, 0)],
)
def test_candidate_detail_identity_mismatch_raises_value_error(
    map_key: int, detail_id: Any
) -> None:
    candidate_id = 9040000001
    detail = _detail(candidate_id)
    detail["match_id"] = detail_id

    with pytest.raises(ValueError, match="candidate detail match_id"):
        _resolve(_context(_game()), [_row(candidate_id)], {map_key: detail})


@pytest.mark.parametrize(
    ("mappings", "reason"),
    [
        ({3000: 9040000001}, "valve_game_already_assigned"),
        ({2000: 9040000002}, "pandascore_game_already_mapped"),
    ],
)
def test_confirmed_one_to_one_mapping_conflicts_block_resolution(
    mappings: dict[int, int], reason: str
) -> None:
    candidate_id = 9040000001

    result = _resolve(
        _context(_game()),
        [_row(candidate_id)],
        {candidate_id: _detail(candidate_id)},
        mappings=mappings,
    )

    assert result.category == "mapping_conflict"
    assert result.reason == reason
    assert result.valve_game_id is None


def test_confirmed_mapping_to_same_pair_does_not_skip_evidence_check() -> None:
    candidate_id = 9040000001

    result = _resolve(
        _context(_game()),
        [_row(candidate_id)],
        {candidate_id: _detail(candidate_id)},
        mappings={2000: candidate_id},
    )

    assert result.category == "resolved"
    assert result.valve_game_id == candidate_id


def test_team_ids_and_different_series_ids_do_not_block_verified_match() -> None:
    # Team IDs are source-local and series_id can vary across games in one Match.
    context = _context(
        _game(4, game_id=739826, begin_at="2026-10-11T18:33:41Z", length=3400,
              winner_id=137073),
        match_id=1709131,
        radiant_id=137073,
        radiant_name="Team Yandex",
        dire_id=1669,
        dire_name="Team Spirit",
    )
    candidate_id = 9040578015
    start_time = 1791743534
    source = {
        "match_id": candidate_id,
        "start_time": start_time,
        "duration": 3400,
        "series_id": 1153562,
        "leagueid": 19102,
    }
    detail = {
        "match_id": candidate_id,
        # These are the timestamps and duration from the saved historical
        # OpenDota detail response.
        "start_time": start_time,
        "duration": 3400,
        "radiant_team": {"team_id": 9823272, "name": "Team Yandex"},
        "dire_team": {"team_id": 7119388, "name": "Team Spirit"},
        "radiant_win": True,
    }

    result = _resolve(
        context,
        [source],
        {candidate_id: detail},
        position=4,
        league_id=19102,
        start_tolerance=180,
        duration_tolerance=5,
    )

    assert result.category == "resolved"
    assert result.valve_game_id == candidate_id
    assert result.candidate_assessments[0].list_start_deltas_seconds == (-87,)
    assert result.candidate_assessments[0].identity_evidence.winner_status == "consistent"


def test_yakult_historical_samples_resolve_with_real_timing() -> None:
    cases = [
        (
            1,
            740347,
            9042629988,
            "2026-10-13T04:02:55Z",
            2488,
            1791865763,
            139363,
            10252232,
            10208034,
            True,
            1154058,
        ),
        (
            2,
            740348,
            9042668580,
            "2026-10-13T05:38:20Z",
            2724,
            1791869668,
            135697,
            10252232,
            9351740,
            False,
            1154073,
        ),
    ]
    for (
        position,
        pandascore_game_id,
        valve_game_id,
        begin_at,
        duration,
        start_time,
        winner_id,
        zenith_id,
        yakult_id,
        radiant_win,
        series_id,
    ) in cases:
        context = _context(
            _game(
                position,
                game_id=pandascore_game_id,
                begin_at=begin_at,
                length=duration,
                winner_id=winner_id,
            ),
            match_id=1745472,
            radiant_id=135697,
            radiant_name="Yakult Brothers",
            dire_id=139363,
            dire_name="Zenith",
        )
        row = _row(
            valve_game_id,
            start_time=start_time,
            duration=duration,
            series_id=series_id,
        )
        detail = _detail(
            valve_game_id,
            start_time=start_time,
            duration=duration,
            radiant_id=zenith_id,
            radiant_name="Zenith",
            dire_id=yakult_id,
            dire_name="Yakult Brothers",
            radiant_win=radiant_win,
            series_id=series_id,
        )

        result = _resolve(
            context,
            [row],
            {valve_game_id: detail},
            position=position,
            start_tolerance=1800,
            duration_tolerance=5,
        )

        assert result.category == "resolved"
        assert result.pandascore_match_id == 1745472
        assert result.game_position == position
        assert result.pandascore_game_id == pandascore_game_id
        assert result.valve_game_id == valve_game_id
        expected_start_delta = 1588 if position == 1 else -232
        assert result.candidate_assessments[0].list_start_deltas_seconds == (
            expected_start_delta,
        )
        assert result.candidate_assessments[0].identity_evidence.participants_status == "supported"
        assert result.candidate_assessments[0].identity_evidence.winner_status == "consistent"


def test_old_blood_missing_dire_and_south_america_outside_window_stay_unresolved() -> None:
    old_blood_id = 9041812996
    context = _context(
        _game(
            2,
            game_id=740236,
            begin_at="2026-10-12T15:14:06Z",
            length=1748,
            winner_id=139406,
        ),
        match_id=1743558,
        radiant_id=139389,
        radiant_name="old blood",
        dire_id=139406,
        dire_name="White Sails",
    )
    old_blood_detail = {
        "match_id": old_blood_id,
        "start_time": 1791818022,
        "duration": 1748,
        "radiant_team_id": 10232798,
        "radiant_team": {"team_id": 10232798, "name": "WhiteSails"},
        "radiant_win": True,
        "series_id": 0,
    }
    old_blood_row = {
        "match_id": old_blood_id,
        "start_time": 1791818022,
        "duration": 1748,
        "series_id": 0,
    }
    old_blood_result = _resolve(
        context,
        [old_blood_row],
        {old_blood_id: old_blood_detail},
        position=2,
    )
    assert old_blood_result.category == "evidence_insufficient"
    assert old_blood_result.valve_game_id is None
    old_blood_evidence = old_blood_result.candidate_assessments[0].identity_evidence
    assert old_blood_evidence.participants_status == "unknown"

    south_america_game = _game(
        3,
        game_id=740340,
        begin_at="2026-10-13T02:31:22Z",
        length=1907,
    )
    south_context = _context(south_america_game, match_id=1744284)
    target_time = datetime.fromisoformat("2026-10-13T02:31:22+00:00").timestamp()
    outside_row = {
        "match_id": 9042461131,
        "start_time": int(target_time) - 10258,
        "duration": 1907,
    }
    south_result = _resolve(
        south_context,
        [outside_row],
        {},
        position=3,
        start_tolerance=1800,
        duration_tolerance=5,
    )
    assert south_result.category == "no_candidates"
    assert south_result.reason == "no_candidate_within_tolerances"
    assert south_result.valve_game_id is None


def test_non_candidate_categories_and_reasons_are_preserved() -> None:
    result = _resolve(
        _context(_game(status="not_started")),
        [_row(9040000001)],
        {},
    )

    assert result.category == "target_not_ready"
    assert result.reason == "target_game_not_started"
    assert result.candidate_assessments == ()
    assert result.valve_game_id is None


def test_resolution_does_not_mutate_any_input() -> None:
    candidate_id = 9040000001
    context = _context(_game(custom={"nested": [1, 2]}))
    rows = [_row(candidate_id, custom={"source": [3, 4]})]
    details = {candidate_id: _detail(candidate_id, custom={"detail": [5, 6]})}
    mappings = {1999: 9040000003}
    before = deepcopy((context, rows, details, mappings))

    _resolve(context, rows, details, mappings=mappings)

    assert (context, rows, details, mappings) == before
