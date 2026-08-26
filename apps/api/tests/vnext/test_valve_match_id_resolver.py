from __future__ import annotations

import asyncio

import pytest

from app.vnext.domain.matches.normalization import (
    NormalizedPandaMatch,
    normalize_panda_match,
)
from app.vnext.domain.matches.valve_match_id_resolver import ValveMatchIdResolver
from app.vnext.providers.opendota.adapter import OpenDotaHTTPError
from app.vnext.providers.pandascore.models import PandaScoreMatch
from tests.vnext.phase2_support import FETCHED_AT, FakeOpenDota, load_fixture


def _normalized_match() -> NormalizedPandaMatch:
    row = PandaScoreMatch.model_validate(load_fixture("pandascore", "match_30001.json"))
    return normalize_panda_match(row, fetched_at=FETCHED_AT)


def test_resolver_returns_unique_valve_match_id() -> None:
    match = _normalized_match()

    decision = asyncio.run(ValveMatchIdResolver(FakeOpenDota()).resolve(match, match.games[0]))

    assert decision.status == "resolved"
    assert decision.resolved_provider_match_id == 40001


def test_resolver_preserves_ambiguous_league_status() -> None:
    opendota = FakeOpenDota()
    opendota.leagues.append(opendota.leagues[0].model_copy(update={"provider_id": 9002}))

    decision = asyncio.run(
        ValveMatchIdResolver(opendota).resolve(_normalized_match(), _normalized_match().games[0])
    )

    assert decision.status == "ambiguous_league"


def test_resolver_preserves_ambiguous_team_status() -> None:
    opendota = FakeOpenDota()
    opendota.teams.append(opendota.teams[0].model_copy(update={"provider_id": 9103}))
    opendota.matches.append(
        opendota.matches[0].model_copy(
            update={"provider_match_id": 40005, "radiant_team_id": 9103}
        )
    )
    match = _normalized_match()

    decision = asyncio.run(ValveMatchIdResolver(opendota).resolve(match, match.games[0]))

    assert decision.status == "ambiguous_team"


def test_resolver_preserves_insufficient_signal_status() -> None:
    match = _normalized_match()

    decision = asyncio.run(ValveMatchIdResolver(FakeOpenDota()).resolve(match, match.games[1]))

    assert decision.status == "insufficient_signals"


def test_resolver_preserves_not_found_status_when_no_game_matches() -> None:
    opendota = FakeOpenDota()
    opendota.matches.clear()
    match = _normalized_match()

    decision = asyncio.run(ValveMatchIdResolver(opendota).resolve(match, match.games[0]))

    assert decision.status == "not_found"


def test_resolver_preserves_ambiguous_match_status() -> None:
    opendota = FakeOpenDota()
    opendota.matches.append(opendota.matches[0].model_copy(update={"provider_match_id": 40005}))
    match = _normalized_match()

    decision = asyncio.run(ValveMatchIdResolver(opendota).resolve(match, match.games[0]))

    assert decision.status == "ambiguous_match"


def test_resolver_does_not_swallow_provider_errors() -> None:
    match = _normalized_match()

    with pytest.raises(OpenDotaHTTPError):
        asyncio.run(
            ValveMatchIdResolver(FakeOpenDota(resolution_available=False)).resolve(
                match,
                match.games[0],
            )
        )


class _CountingOpenDota(FakeOpenDota):
    def __init__(self) -> None:
        super().__init__()
        self.league_calls = 0
        self.league_match_calls = 0
        self.team_calls = 0

    async def list_leagues(self):
        self.league_calls += 1
        return await super().list_leagues()

    async def list_league_matches(self, league_id: int):
        self.league_match_calls += 1
        return await super().list_league_matches(league_id)

    async def list_teams(self):
        self.team_calls += 1
        return await super().list_teams()


def test_resolve_many_loads_shared_resolution_data_once() -> None:
    opendota = _CountingOpenDota()
    match = _normalized_match()

    decisions = asyncio.run(ValveMatchIdResolver(opendota).resolve_many(match, match.games))

    assert [decision.status for decision in decisions] == ["resolved", "insufficient_signals"]
    assert opendota.league_calls == 1
    assert opendota.league_match_calls == 1
    assert opendota.team_calls == 1
