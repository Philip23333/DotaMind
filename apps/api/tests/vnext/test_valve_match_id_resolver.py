"""Batch OpenDota evidence-loading contracts for Valve match resolution."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

from app.vnext.domain.matches.normalization import normalize_panda_match
from app.vnext.domain.matches.valve_match_id_resolver import ValveMatchIdResolver
from app.vnext.providers.common import ProviderBatch
from app.vnext.providers.opendota.adapter import OpenDotaTimeoutError
from app.vnext.providers.opendota.models import OpenDotaLeague, OpenDotaLeagueMatch, OpenDotaTeam
from app.vnext.providers.pandascore.models import PandaScoreMatch

_FETCHED_AT = datetime(2026, 8, 31, tzinfo=timezone.utc)
_GAME_START = datetime(2026, 8, 20, 8, 5, tzinfo=timezone.utc)


def _normalized_match(
    identifier: int,
    *,
    series_name: str = "The International",
    series_year: int = 2026,
) -> object:
    return normalize_panda_match(
        PandaScoreMatch.model_validate(
            {
                "id": identifier,
                "name": f"{series_name} match {identifier}",
                "status": "finished",
                "serie": {"id": identifier, "name": series_name, "year": series_year},
                "opponents": [
                    {"type": "Team", "opponent": {"id": 11, "name": "Alpha"}},
                    {"type": "Team", "opponent": {"id": 12, "name": "Beta"}},
                ],
                "games": [
                    {
                        "id": identifier * 10 + position,
                        "position": position,
                        "status": "finished",
                        "begin_at": _GAME_START.isoformat().replace("+00:00", "Z"),
                        "length": 2400,
                        "winner": {"id": 11},
                    }
                    for position in range(1, 4)
                ],
            }
        ),
        fetched_at=_FETCHED_AT,
    )


def _league(identifier: int, name: str) -> OpenDotaLeague:
    return OpenDotaLeague.model_validate({"leagueid": identifier, "name": name})


def _league_match(identifier: int, league_id: int) -> OpenDotaLeagueMatch:
    return OpenDotaLeagueMatch.model_validate(
        {
            "match_id": identifier,
            "leagueid": league_id,
            "start_time": int(_GAME_START.timestamp()),
            "duration": 2400,
            "radiant_team_id": 101,
            "dire_team_id": 102,
            "radiant_win": True,
        }
    )


class RecordingOpenDota:
    def __init__(
        self,
        leagues: list[OpenDotaLeague],
        league_matches: dict[int, list[OpenDotaLeagueMatch]],
        *,
        fail_leagues: bool = False,
        fail_teams: bool = False,
        failed_league_ids: set[int] | None = None,
    ) -> None:
        self.leagues = leagues
        self.league_matches = league_matches
        self.fail_leagues = fail_leagues
        self.fail_teams = fail_teams
        self.failed_league_ids = failed_league_ids or set()
        self.list_leagues_calls = 0
        self.list_teams_calls = 0
        self.list_league_match_calls: list[int] = []

    async def list_leagues(self) -> ProviderBatch[OpenDotaLeague]:
        self.list_leagues_calls += 1
        if self.fail_leagues:
            raise OpenDotaTimeoutError("leagues unavailable")
        return ProviderBatch(self.leagues, _FETCHED_AT)

    async def list_teams(self) -> ProviderBatch[OpenDotaTeam]:
        self.list_teams_calls += 1
        if self.fail_teams:
            raise OpenDotaTimeoutError("teams unavailable")
        return ProviderBatch(
            [
                OpenDotaTeam.model_validate({"team_id": 101, "name": "Alpha"}),
                OpenDotaTeam.model_validate({"team_id": 102, "name": "Beta"}),
            ],
            _FETCHED_AT,
        )

    async def list_league_matches(self, league_id: int) -> ProviderBatch[OpenDotaLeagueMatch]:
        self.list_league_match_calls.append(league_id)
        if league_id in self.failed_league_ids:
            raise OpenDotaTimeoutError("league matches unavailable")
        return ProviderBatch(self.league_matches[league_id], _FETCHED_AT)


def test_batch_resolver_loads_shared_evidence_once_for_ten_matches() -> None:
    league_id = 19719
    adapter = RecordingOpenDota(
        [_league(league_id, "The International 2026")],
        {league_id: [_league_match(9001, league_id)]},
    )
    resolver = ValveMatchIdResolver(adapter)  # type: ignore[arg-type]
    matches = [_normalized_match(identifier) for identifier in range(1, 11)]

    outcomes = asyncio.run(resolver.resolve_many_matches(matches))

    assert adapter.list_leagues_calls == 1
    assert adapter.list_teams_calls == 1
    assert adapter.list_league_match_calls == [league_id]
    assert all(
        outcome.decisions is not None
        and [decision.status for decision in outcome.decisions] == ["resolved"] * 3
        for outcome in outcomes
    )


def test_batch_resolver_loads_each_unique_league_once() -> None:
    league_ids = [101, 102, 103]
    series = ["Event A", "Event B", "Event C"]
    adapter = RecordingOpenDota(
        [
            _league(identifier, f"{name} 2026")
            for identifier, name in zip(league_ids, series, strict=True)
        ],
        {identifier: [_league_match(identifier * 10, identifier)] for identifier in league_ids},
    )
    resolver = ValveMatchIdResolver(adapter)  # type: ignore[arg-type]
    matches = [
        _normalized_match(index, series_name=name)
        for index, name in enumerate(series, start=1)
        for _ in range(3)
    ]

    outcomes = asyncio.run(resolver.resolve_many_matches(matches))

    assert adapter.list_leagues_calls == 1
    assert adapter.list_teams_calls == 1
    assert sorted(adapter.list_league_match_calls) == league_ids
    assert all(outcome.unavailable is False for outcome in outcomes)


def test_batch_resolver_skips_opendota_for_missing_series_year() -> None:
    adapter = RecordingOpenDota([], {})
    resolver = ValveMatchIdResolver(adapter)  # type: ignore[arg-type]
    match = replace(_normalized_match(1), series_year=None)

    outcome = asyncio.run(resolver.resolve_many_matches([match]))[0]

    assert adapter.list_leagues_calls == 0
    assert adapter.list_teams_calls == 0
    assert adapter.list_league_match_calls == []
    assert outcome.unavailable is False
    assert outcome.decisions is not None
    assert [decision.status for decision in outcome.decisions] == ["insufficient_signals"] * 3


def test_batch_resolver_degrades_only_the_failed_league() -> None:
    leagues = [_league(1, "Event A 2026"), _league(2, "Event B 2026")]
    adapter = RecordingOpenDota(
        leagues,
        {1: [_league_match(101, 1)], 2: [_league_match(201, 2)]},
        failed_league_ids={2},
    )
    resolver = ValveMatchIdResolver(adapter)  # type: ignore[arg-type]

    first, second = asyncio.run(
        resolver.resolve_many_matches(
            [
                _normalized_match(1, series_name="Event A"),
                _normalized_match(2, series_name="Event B"),
            ]
        )
    )

    assert first.unavailable is False
    assert first.decisions is not None
    assert [decision.status for decision in first.decisions] == ["resolved"] * 3
    assert second.unavailable is True
    assert second.decisions is None


def test_global_opendota_failures_do_not_overwrite_insufficient_signals() -> None:
    eligible = _normalized_match(1)
    insufficient = replace(_normalized_match(2), series_year=None)

    league_failure = RecordingOpenDota([], {}, fail_leagues=True)
    league_outcomes = asyncio.run(
        ValveMatchIdResolver(league_failure).resolve_many_matches([eligible, insufficient])  # type: ignore[arg-type]
    )
    assert [outcome.unavailable for outcome in league_outcomes] == [True, False]
    assert league_outcomes[1].decisions is not None
    assert [decision.status for decision in league_outcomes[1].decisions] == [
        "insufficient_signals"
    ] * 3

    team_failure = RecordingOpenDota(
        [_league(19719, "The International 2026")],
        {19719: [_league_match(9001, 19719)]},
        fail_teams=True,
    )
    team_outcomes = asyncio.run(
        ValveMatchIdResolver(team_failure).resolve_many_matches([eligible, insufficient])  # type: ignore[arg-type]
    )
    assert [outcome.unavailable for outcome in team_outcomes] == [True, False]
    assert team_failure.list_league_match_calls == []


def test_batch_resolver_retains_deterministic_not_found_and_ambiguous_league_statuses() -> None:
    no_match_adapter = RecordingOpenDota(
        [_league(1, "The International 2026")],
        {1: []},
    )
    no_match = asyncio.run(
        ValveMatchIdResolver(no_match_adapter).resolve_many_matches([_normalized_match(1)])  # type: ignore[arg-type]
    )[0]
    assert no_match.decisions is not None
    assert [decision.status for decision in no_match.decisions] == ["not_found"] * 3

    ambiguous_adapter = RecordingOpenDota(
        [_league(1, "The International 2026"), _league(2, "The International 2026")],
        {1: [], 2: []},
    )
    ambiguous = asyncio.run(
        ValveMatchIdResolver(ambiguous_adapter).resolve_many_matches([_normalized_match(1)])  # type: ignore[arg-type]
    )[0]
    assert ambiguous.decisions is not None
    assert [decision.status for decision in ambiguous.decisions] == ["ambiguous_league"] * 3
    assert ambiguous_adapter.list_teams_calls == 0
    assert ambiguous_adapter.list_league_match_calls == []
