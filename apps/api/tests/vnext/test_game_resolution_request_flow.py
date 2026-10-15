from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from functools import wraps
from typing import Any

import pytest

from app.vnext.providers.match_resolution import (
    GameResolutionReadPolicy,
    PandaScoreOpenDotaGameResolutionProvider,
    ResolutionBudgetExceeded,
)
from app.vnext.providers.opendota.game_detail import OpenDotaGameRecord
from app.vnext.tools.errors import StructuredToolError

_START_TIME = 1_791_743_534
_VALVE_ID = 9_040_578_015
_DEFAULT_MATCH = object()


def _async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def _context(
    *,
    games: list[dict[str, Any]] | None = None,
    match_id: int = 1_709_131,
    league_name: str = "BLAST SLAM",
) -> dict[str, Any]:
    return {
        "id": match_id,
        "league": {"name": league_name, "extra_league_fact": "retained"},
        "serie": {"season": "8", "year": 2026, "name": "Season 8"},
        "opponents": [
            {"opponent": {"id": 137073, "name": "Team Yandex"}},
            {"opponent": {"id": 1669, "name": "Team Spirit"}},
        ],
        "games": games
        if games is not None
        else [
            {
                "id": 739826,
                "position": 4,
                "begin_at": "2026-10-11T18:33:41Z",
                "length": 3400,
                "winner": {"id": 137073, "type": "Team"},
                "winner_id": 137073,
                "winner_type": "Team",
                "unmodeled_game_fact": {"keep": [0, False, None]},
            }
        ],
        "unmodeled_match_fact": {"preserve": True},
    }


def _league(league_id: int = 19102, name: str = "BLAST SLAM VIII"):
    return {"leagueid": league_id, "name": name, "source_extension": {"x": 0}}


def _row(valve_id: int = _VALVE_ID, *, league_id: int = 19102):
    return {
        "match_id": valve_id,
        "start_time": _START_TIME,
        "duration": 3400,
        "leagueid": league_id,
        "series_id": 1153562,
        "unknown_zero": 0,
        "unknown_false": False,
        "unknown_null": None,
        "unknown_list_order": ["first", "second"],
    }


def _detail(
    valve_id: int = _VALVE_ID,
    *,
    radiant_name: str = "Team Yandex",
    dire_name: str = "Team Spirit",
    start_time: int = _START_TIME,
    duration: int = 3400,
):
    return OpenDotaGameRecord(
        match_id=valve_id,
        provider="opendota",
        retrieved_at=datetime(2026, 10, 14, tzinfo=UTC),
        data={
            "match_id": valve_id,
            "start_time": start_time,
            "duration": duration,
            "radiant_team": {"team_id": 9823272, "name": radiant_name},
            "dire_team": {"team_id": 7119388, "name": dire_name},
            "radiant_win": True,
            "unmodeled_detail_fact": {"zero": 0, "false": False, "null": None},
        },
    )


def _policy(
    *,
    max_leagues: int = 10,
    max_candidate_details: int = 10,
    max_requests: int = 30,
) -> GameResolutionReadPolicy:
    return GameResolutionReadPolicy(
        start_time_tolerance_seconds=180,
        duration_tolerance_seconds=5,
        max_leagues=max_leagues,
        max_candidate_details=max_candidate_details,
        max_requests=max_requests,
    )


class _FakePandaScore:
    def __init__(
        self,
        calls: list[tuple[str, int | None]],
        match: dict[str, Any] | None,
        *,
        fail: str | None = None,
        entered: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
    ) -> None:
        self.calls = calls
        self.match = match
        self.fail = fail
        self.entered = entered
        self.release = release

    async def get_match_context(self, match_id: int):
        self.calls.append(("match", match_id))
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.fail == "match":
            raise _provider_error()
        return self.match


class _FakeDiscovery:
    def __init__(
        self,
        calls: list[tuple[str, int | None]],
        leagues: list[dict[str, Any]],
        league_matches: dict[int, list[dict[str, Any]]],
        *,
        fail: str | None = None,
    ) -> None:
        self.calls = calls
        self.leagues = leagues
        self.league_matches = league_matches
        self.fail = fail

    async def get_leagues(self):
        self.calls.append(("leagues", None))
        if self.fail == "leagues":
            raise _provider_error()
        return self.leagues

    async def get_league_matches(self, league_id: int):
        self.calls.append(("league_matches", league_id))
        if self.fail == "league_matches":
            raise _provider_error()
        return self.league_matches[league_id]


class _FakeGameDetail:
    def __init__(
        self,
        calls: list[tuple[str, int | None]],
        details: dict[int, OpenDotaGameRecord],
        *,
        fail: str | None = None,
    ) -> None:
        self.calls = calls
        self.details = details
        self.fail = fail

    async def get_game_record(self, match_id: int):
        self.calls.append(("game_detail", match_id))
        if self.fail == "game_detail":
            raise _provider_error()
        return self.details[match_id]


def _provider(
    *,
    match: dict[str, Any] | None | object = _DEFAULT_MATCH,
    leagues: list[dict[str, Any]] | None = None,
    league_matches: dict[int, list[dict[str, Any]]] | None = None,
    details: dict[int, OpenDotaGameRecord] | None = None,
    fail: str | None = None,
    entered: asyncio.Event | None = None,
    release: asyncio.Event | None = None,
):
    calls: list[tuple[str, int | None]] = []
    match_context = _context() if match is _DEFAULT_MATCH else match
    provider = PandaScoreOpenDotaGameResolutionProvider(
        _FakePandaScore(
            calls,
            match_context,  # type: ignore[arg-type]
            fail=fail,
            entered=entered,
            release=release,
        ),
        _FakeDiscovery(
            calls,
            [_league()] if leagues is None else leagues,
            {19102: [_row()]} if league_matches is None else league_matches,
            fail=fail,
        ),  # type: ignore[arg-type]
        _FakeGameDetail(
            calls,
            {_VALVE_ID: _detail()} if details is None else details,
            fail=fail,
        ),  # type: ignore[arg-type]
    )
    return provider, calls


def _provider_error() -> StructuredToolError:
    return StructuredToolError(
        "provider_timeout",
        "source request timed out",
        {"provider": "opendota", "category": "timeout"},
    )


@_async_test
async def test_blast_game_four_resolves_through_complete_read_flow() -> None:
    provider, calls = _provider()

    attempt = await provider.resolve(
        1_709_131,
        4,
        policy=_policy(),
        confirmed_mappings={},
    )

    assert attempt.stage == "resolution"
    assert attempt.requests_started == 4
    assert attempt.resolution_result is not None
    assert attempt.resolution_result.category == "resolved"
    assert attempt.resolution_result.valve_game_id == _VALVE_ID
    assert attempt.resolution_result.pandascore_game_id == 739826
    assert calls == [
        ("match", 1_709_131),
        ("leagues", None),
        ("league_matches", 19102),
        ("game_detail", _VALVE_ID),
    ]
    assert attempt.retrieved_at.tzinfo is not None
    assert attempt.candidate_details[_VALVE_ID].provider == "opendota"
    assert attempt.candidate_details[_VALVE_ID].retrieved_at == datetime(
        2026, 10, 14, tzinfo=UTC
    )


@_async_test
async def test_all_selected_leagues_are_evaluated_before_resolving() -> None:
    first_id, second_id = _VALVE_ID, _VALVE_ID + 1
    provider, calls = _provider(
        leagues=[_league(19102), _league(19103)],
        league_matches={
            19102: [_row(first_id, league_id=19102)],
            19103: [_row(second_id, league_id=19103)],
        },
        details={first_id: _detail(first_id), second_id: _detail(second_id)},
    )

    attempt = await provider.resolve(1_709_131, 4, policy=_policy(), confirmed_mappings={})

    assert attempt.resolution_result is not None
    assert attempt.resolution_result.category == "ambiguous"
    assert attempt.resolution_result.valve_game_id is None
    assert [call[0] for call in calls] == [
        "match",
        "leagues",
        "league_matches",
        "league_matches",
        "game_detail",
        "game_detail",
    ]
    assert attempt.resolution_result.searched_league_ids == (19102, 19103)


@_async_test
async def test_same_valve_game_in_multiple_lists_reads_detail_once() -> None:
    valve_id = _VALVE_ID
    provider, calls = _provider(
        leagues=[_league(19102), _league(19103)],
        league_matches={
            19102: [_row(valve_id, league_id=19102)],
            19103: [_row(valve_id, league_id=19103)],
        },
        details={valve_id: _detail(valve_id)},
    )

    attempt = await provider.resolve(1_709_131, 4, policy=_policy(), confirmed_mappings={})

    assert calls.count(("game_detail", valve_id)) == 1
    assert attempt.resolution_result is not None
    assert attempt.resolution_result.category == "resolved"
    group = attempt.resolution_result.candidate_assessments[0]
    assert len(group.league_assessments) == 2


@_async_test
async def test_repeated_league_id_is_requested_once_and_all_source_rows_are_retained() -> None:
    first, repeated = _league(19102), _league(19102, "BLAST SLAM 8")
    provider, calls = _provider(
        leagues=[first, repeated],
        league_matches={19102: [_row()]},
    )

    attempt = await provider.resolve(
        1_709_131,
        4,
        policy=_policy(max_leagues=2),
        confirmed_mappings={},
    )

    assert calls.count(("league_matches", 19102)) == 1
    assert attempt.opendota_leagues == (first, repeated)
    assert attempt.league_candidate_result is not None
    assert len(attempt.league_candidate_result.candidates) == 2


@_async_test
async def test_missing_match_and_invalid_target_stop_before_opendota_reads() -> None:
    no_match_provider, no_match_calls = _provider(match=None)
    no_match = await no_match_provider.resolve(
        1_709_131, 4, policy=_policy(), confirmed_mappings={}
    )
    invalid_target_provider, invalid_target_calls = _provider(
        match=_context(games=[])
    )
    invalid_target = await invalid_target_provider.resolve(
        1_709_131, 4, policy=_policy(), confirmed_mappings={}
    )

    assert no_match.reason == "match_not_found"
    assert no_match.stage == "match_context"
    assert no_match_calls == [("match", 1_709_131)]
    assert invalid_target.target_game_result is not None
    assert invalid_target.target_game_result.category == "target_game_not_found"
    assert invalid_target_calls == [("match", 1_709_131)]


@_async_test
async def test_no_league_candidate_does_not_read_lists_or_details() -> None:
    provider, calls = _provider(
        leagues=[_league(19102, "DreamLeague Season 30")],
        league_matches={},
    )

    attempt = await provider.resolve(1_709_131, 4, policy=_policy(), confirmed_mappings={})

    assert attempt.stage == "league_candidates"
    assert attempt.league_candidate_result is not None
    assert attempt.league_candidate_result.category == "no_candidates"
    assert calls == [("match", 1_709_131), ("leagues", None)]


@_async_test
async def test_league_candidate_overflow_is_not_truncated_or_read() -> None:
    provider, calls = _provider(
        leagues=[_league(19102), _league(19103)],
        league_matches={19102: [], 19103: []},
    )

    with pytest.raises(ResolutionBudgetExceeded) as raised:
        await provider.resolve(
            1_709_131,
            4,
            policy=_policy(max_leagues=1),
            confirmed_mappings={},
        )

    error = raised.value
    assert (error.operation, error.limit_name, error.limit, error.required) == (
        "league_candidates",
        "max_leagues",
        1,
        2,
    )
    assert error.remaining is None
    assert error.requests_started == 2
    assert calls == [("match", 1_709_131), ("leagues", None)]


@_async_test
async def test_insufficient_list_request_budget_does_not_start_list_phase() -> None:
    provider, calls = _provider(
        leagues=[_league(19102), _league(19103)],
        league_matches={19102: [], 19103: []},
    )

    with pytest.raises(ResolutionBudgetExceeded) as raised:
        await provider.resolve(
            1_709_131,
            4,
            policy=_policy(max_requests=3),
            confirmed_mappings={},
        )

    error = raised.value
    assert error.operation == "league_matches"
    assert error.limit_name == "max_requests"
    assert error.required == 2
    assert error.remaining == 1
    assert error.requests_started == 2
    assert calls == [("match", 1_709_131), ("leagues", None)]


@_async_test
async def test_request_budget_is_checked_before_each_single_adapter_read() -> None:
    provider, calls = _provider()

    with pytest.raises(ResolutionBudgetExceeded) as raised:
        await provider.resolve(
            1_709_131,
            4,
            policy=_policy(max_requests=1),
            confirmed_mappings={},
        )

    error = raised.value
    assert error.operation == "leagues"
    assert error.limit_name == "max_requests"
    assert error.required == 1
    assert error.remaining == 0
    assert error.requests_started == 1
    assert calls == [("match", 1_709_131)]


@_async_test
async def test_detail_count_overflow_does_not_start_detail_phase() -> None:
    first, second = _VALVE_ID, _VALVE_ID + 1
    provider, calls = _provider(
        leagues=[_league(19102), _league(19103)],
        league_matches={
            19102: [_row(first, league_id=19102)],
            19103: [_row(second, league_id=19103)],
        },
        details={first: _detail(first), second: _detail(second)},
    )

    with pytest.raises(ResolutionBudgetExceeded) as raised:
        await provider.resolve(
            1_709_131,
            4,
            policy=_policy(max_candidate_details=1),
            confirmed_mappings={},
        )

    error = raised.value
    assert (error.operation, error.limit_name, error.limit, error.required) == (
        "candidate_details",
        "max_candidate_details",
        1,
        2,
    )
    assert error.requests_started == 4
    assert not any(operation == "game_detail" for operation, _ in calls)


@_async_test
async def test_insufficient_detail_request_budget_does_not_start_detail_phase() -> None:
    provider, calls = _provider()

    with pytest.raises(ResolutionBudgetExceeded) as raised:
        await provider.resolve(
            1_709_131,
            4,
            policy=_policy(max_requests=3),
            confirmed_mappings={},
        )

    error = raised.value
    assert error.operation == "candidate_details"
    assert error.limit_name == "max_requests"
    assert error.required == 1
    assert error.remaining == 0
    assert error.requests_started == 3
    assert not any(operation == "game_detail" for operation, _ in calls)


@_async_test
async def test_explicitly_empty_league_list_reaches_no_candidate_resolution() -> None:
    provider, calls = _provider(league_matches={19102: []})

    attempt = await provider.resolve(1_709_131, 4, policy=_policy(), confirmed_mappings={})

    assert attempt.stage == "resolution"
    assert attempt.requests_started == 3
    assert attempt.resolution_result is not None
    assert attempt.resolution_result.category == "no_candidates"
    assert attempt.resolution_result.reason == "no_candidates_in_selected_leagues"
    assert calls == [
        ("match", 1_709_131),
        ("leagues", None),
        ("league_matches", 19102),
    ]


@_async_test
@pytest.mark.parametrize(
    ("fail", "expected_operation", "expected_calls"),
    [
        ("match", "match_context", 1),
        ("leagues", "leagues", 2),
        ("league_matches", "league_matches", 3),
        ("game_detail", "game_detail", 4),
    ],
)
async def test_provider_errors_preserve_classification_and_stop(
    fail: str,
    expected_operation: str,
    expected_calls: int,
) -> None:
    provider, calls = _provider(fail=fail)

    with pytest.raises(StructuredToolError) as raised:
        await provider.resolve(1_709_131, 4, policy=_policy(), confirmed_mappings={})

    error = raised.value
    assert error.code == "provider_timeout"
    assert error.details["provider"] == "opendota"
    assert error.details["category"] == "timeout"
    assert error.details["operation"] == expected_operation
    assert error.details["requests_started"] == expected_calls
    assert len(calls) == expected_calls


@_async_test
async def test_cancelled_adapter_wait_propagates_without_followup_reads() -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    provider, calls = _provider(entered=entered, release=release)
    task = asyncio.create_task(
        provider.resolve(1_709_131, 4, policy=_policy(), confirmed_mappings={})
    )
    await asyncio.wait_for(entered.wait(), timeout=1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls == [("match", 1_709_131)]


@_async_test
@pytest.mark.parametrize("match_id,position", [(True, 4), (1_709_131, False), (0, 4)])
async def test_invalid_identity_inputs_are_rejected_before_any_read(
    match_id: Any,
    position: Any,
) -> None:
    provider, calls = _provider()

    with pytest.raises(ValueError):
        await provider.resolve(
            match_id,
            position,
            policy=_policy(),
            confirmed_mappings={},
        )

    assert calls == []


@_async_test
@pytest.mark.parametrize(
    "mappings",
    [{True: 10}, {1: False}, {0: 10}],
)
async def test_invalid_confirmed_mappings_are_rejected_before_any_read(
    mappings: dict[Any, Any],
) -> None:
    provider, calls = _provider()

    with pytest.raises(ValueError):
        await provider.resolve(
            1_709_131,
            4,
            policy=_policy(),
            confirmed_mappings=mappings,  # type: ignore[arg-type]
        )

    assert calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("start_time_tolerance_seconds", True),
        ("duration_tolerance_seconds", -1),
        ("max_leagues", 0),
        ("max_candidate_details", 1.5),
        ("max_requests", False),
    ],
)
def test_invalid_policy_values_are_rejected(field: str, value: Any) -> None:
    values: dict[str, Any] = {
        "start_time_tolerance_seconds": 0,
        "duration_tolerance_seconds": 0,
        "max_leagues": 1,
        "max_candidate_details": 1,
        "max_requests": 1,
    }
    values[field] = value

    with pytest.raises(ValueError):
        GameResolutionReadPolicy(**values)


@_async_test
async def test_source_extensions_and_provider_metadata_are_retained_without_mutation() -> None:
    match = _context()
    league = _league()
    row = _row()
    detail = _detail()
    mappings = {739_827: _VALVE_ID + 1}
    before = deepcopy((match, [league], {19102: [row]}, detail, mappings))
    provider, _ = _provider(
        match=match,
        leagues=[league],
        league_matches={19102: [row]},
        details={_VALVE_ID: detail},
    )

    attempt = await provider.resolve(
        1_709_131, 4, policy=_policy(), confirmed_mappings=mappings
    )

    assert (match, [league], {19102: [row]}, detail, mappings) == before
    assert attempt.pandascore_match_context is match
    assert attempt.pandascore_match_context["unmodeled_match_fact"] == {
        "preserve": True
    }
    assert attempt.opendota_leagues == (league,)
    assert attempt.opendota_leagues[0]["source_extension"] == {"x": 0}
    assert attempt.league_matches_by_id[19102] == (row,)
    assert attempt.league_matches_by_id[19102][0]["unknown_list_order"] == [
        "first",
        "second",
    ]
    retained_detail = attempt.candidate_details[_VALVE_ID]
    assert retained_detail.retrieved_at == detail.retrieved_at
    assert retained_detail.data["unmodeled_detail_fact"] == {
        "zero": 0,
        "false": False,
        "null": None,
    }
