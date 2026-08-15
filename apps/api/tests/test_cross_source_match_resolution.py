from __future__ import annotations

import pytest

from app.integrations.match_resolution.valve_match_resolver import ValveMatchResolver
from app.integrations.opendota.leagues import OpenDotaLeague, OpenDotaLeagueMatch


class FakeLeagues:
    def __init__(self, leagues: list[OpenDotaLeague], matches: list[OpenDotaLeagueMatch]):
        self.leagues = leagues
        self.matches = matches

    async def get_all(self) -> list[OpenDotaLeague]:
        return self.leagues

    async def get_matches(self, league_id: int) -> list[OpenDotaLeagueMatch]:
        return [row for row in self.matches if row.opendota_league_id == league_id]


class FakeTeams:
    def __init__(
        self,
        teams: list[dict],
        matches_by_team_id: dict[int, list[dict] | Exception] | None = None,
    ):
        self.teams = teams
        self.matches_by_team_id = matches_by_team_id or {}
        self.match_calls: list[int] = []

    async def get_all(self) -> list[dict]:
        return self.teams

    async def get_matches(self, team_id: int) -> list[dict]:
        self.match_calls.append(team_id)
        value = self.matches_by_team_id.get(team_id, [])
        if isinstance(value, Exception):
            raise value
        return value


def _competition(**overrides):
    value = {
        "series_id": 10828,
        "series_name": "The International",
        "year": 2026,
    }
    value.update(overrides)
    return value


def _game(**overrides):
    value = {
        "pandascore_match_id": 1631694,
        "pandascore_game_id": 738652,
        "game_position": 1,
        "game_begin_at": "2026-08-13T09:32:32+00:00",
        "length_seconds": 3227,
        "teams": [
            {"pandascore_team_id": 129609, "name": "Nigma Galaxy", "acronym": "NGX"},
            {"pandascore_team_id": 121771, "name": "OG", "acronym": "OG"},
        ],
        "winner_pandascore_team_id": 129609,
    }
    value.update(overrides)
    return value


def _resolver(
    matches: list[OpenDotaLeagueMatch] | None = None,
    teams=None,
    matches_by_team_id: dict[int, list[dict] | Exception] | None = None,
):
    league = OpenDotaLeague(opendota_league_id=19719, name="The International 2026")
    rows = matches or [
        OpenDotaLeagueMatch(
            valve_match_id=8943244303,
            opendota_league_id=19719,
            opendota_series_id=1130066,
            start_time=1786613552,
            duration=3227,
            radiant_team_id=10136357,
            dire_team_id=2586976,
            radiant_win=True,
        ),
        OpenDotaLeagueMatch(
            valve_match_id=8943324841,
            opendota_league_id=19719,
            opendota_series_id=1130066,
            start_time=1786618471,
            duration=4461,
            radiant_team_id=2586976,
            dire_team_id=10136357,
            radiant_win=False,
        ),
    ]
    team_rows = teams or [
        {"team_id": 10136357, "name": "Nigma Galaxy", "tag": "NGX"},
        {"team_id": 2586976, "name": "OG", "tag": "OG"},
    ]
    return ValveMatchResolver(
        FakeLeagues([league], rows),
        FakeTeams(team_rows, matches_by_team_id),
    )


def _duplicate_team_rows() -> list[dict]:
    return [
        {"team_id": 10136357, "name": "Nigma Galaxy", "tag": "NGX"},
        {"team_id": 7554697, "name": "Nigma Galaxy", "tag": "NGX"},
        {"team_id": 2586976, "name": "OG", "tag": "OG"},
    ]


def _team_match(league_id: int, match_id: int, league_name: str | None = None) -> dict:
    row = {"leagueid": league_id, "match_id": match_id}
    if league_name is not None:
        row["league_name"] = league_name
    return row


@pytest.mark.anyio
async def test_resolves_known_game_with_reversed_team_order_support() -> None:
    result = await _resolver().resolve(_competition(), _game())
    assert result.status == "resolved"
    assert result.match is not None
    assert result.match.valve_match_id == 8943244303
    assert result.mapping is not None
    assert result.mapping.method == "inferred_cross_source"
    assert result.mapping.matched_on[-1] == "winner"


@pytest.mark.anyio
async def test_league_participation_resolves_duplicate_team_and_audits_mapping() -> None:
    resolver = _resolver(
        teams=_duplicate_team_rows(),
        matches_by_team_id={
            10136357: [_team_match(19719, 8943244303)],
            7554697: [_team_match(19656, 8940000000)],
        },
    )
    result = await resolver.resolve(_competition(), _game())
    assert result.status == "resolved"
    assert result.match is not None and result.match.valve_match_id == 8943244303
    assert result.mapping is not None
    assert "team_league_participation" in result.mapping.matched_on
    assert result.teams[0]["opendota_team_id"] == 10136357
    assert result.teams[0]["resolution_method"] == "league_participation"
    assert result.teams[0]["target_league_id"] == 19719
    assert result.teams[0]["league_match_count"] == 1
    assert result.teams[0]["sample_match_ids"] == [8943244303]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("matches_by_team_id", "reason"),
    [
        (
            {
                10136357: [_team_match(19656, 8940000001)],
                7554697: [_team_match(19656, 8940000002)],
            },
            "no_candidate_in_target_league",
        ),
        (
            {
                10136357: [_team_match(19719, 8940000003)],
                7554697: [_team_match(19719, 8940000004)],
            },
            "multiple_candidates_in_target_league",
        ),
        (
            {
                10136357: [
                    _team_match(
                        19892,
                        8940000005,
                        "The International 2026 - Regional Qualifier Europe",
                    )
                ],
                7554697: [],
            },
            "no_candidate_in_target_league",
        ),
    ],
)
async def test_duplicate_team_league_participation_remains_explicit(
    matches_by_team_id, reason
) -> None:
    resolver = _resolver(
        teams=_duplicate_team_rows(),
        matches_by_team_id=matches_by_team_id,
    )
    result = await resolver.resolve(_competition(), _game())
    assert result.status == "ambiguous_team"
    assert result.teams[0]["reason"] == reason
    assert result.teams[0]["target_league_id"] == 19719


@pytest.mark.anyio
async def test_unique_team_does_not_fetch_team_matches() -> None:
    resolver = _resolver()
    result = await resolver.resolve(_competition(), _game())
    assert result.status == "resolved"
    assert resolver.teams.match_calls == []


@pytest.mark.anyio
async def test_team_matches_upstream_error_is_not_converted_to_ambiguity() -> None:
    resolver = _resolver(
        teams=_duplicate_team_rows(),
        matches_by_team_id={10136357: RuntimeError("upstream failed")},
    )
    with pytest.raises(RuntimeError, match="upstream failed"):
        await resolver.resolve(_competition(), _game())


@pytest.mark.anyio
async def test_resolves_when_pandascore_team_order_is_reversed() -> None:
    game = _game(
        teams=[
            {"pandascore_team_id": 121771, "name": "OG", "acronym": "OG"},
            {"pandascore_team_id": 129609, "name": "Nigma Galaxy", "acronym": "NGX"},
        ]
    )
    result = await _resolver().resolve(_competition(), game)
    assert result.status == "resolved"
    assert result.match is not None and result.match.valve_match_id == 8943244303


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("competition", "game", "expected"),
    [
        ({"series_name": "Unknown", "year": 2026}, _game(), "league_not_found"),
        (_competition(), _game(game_begin_at=None), "insufficient_signals"),
        (_competition(), _game(length_seconds=100), "not_found"),
        (_competition(), _game(game_position=2), "not_found"),
        (_competition(), _game(winner_pandascore_team_id=121771), "not_found"),
    ],
)
async def test_resolution_statuses_are_explicit(competition, game, expected) -> None:
    assert (await _resolver().resolve(competition, game)).status == expected


@pytest.mark.anyio
async def test_ambiguous_league_and_team_are_not_silently_selected() -> None:
    duplicate_leagues = [
        OpenDotaLeague(opendota_league_id=19719, name="The International 2026"),
        OpenDotaLeague(opendota_league_id=19720, name="The International 2026"),
    ]
    result = await ValveMatchResolver(
        FakeLeagues(duplicate_leagues, []),
        FakeTeams([]),
    ).resolve(_competition(), _game())
    assert result.status == "ambiguous_league"

    result = await _resolver(teams=_duplicate_team_rows()).resolve(_competition(), _game())
    assert result.status == "ambiguous_team"
