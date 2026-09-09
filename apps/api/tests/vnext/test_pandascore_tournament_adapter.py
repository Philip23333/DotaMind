from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.vnext.capabilities.esports.tournament import TournamentSearchInput
from app.vnext.providers.pandascore.client import PandaScoreClient
from app.vnext.providers.pandascore.tournament_adapter import PandaScoreTournamentAdapter


def _adapter(handler) -> PandaScoreTournamentAdapter:
    client = PandaScoreClient(
        base_url="https://api.pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    return PandaScoreTournamentAdapter(client)


def _team(
    team_id: int,
    name: str,
    acronym: str,
    location: str,
    slug: str,
    image_url: str,
) -> dict[str, Any]:
    return {
        "id": team_id,
        "name": name,
        "acronym": acronym,
        "location": location,
        "slug": slug,
        "image_url": image_url,
        "players": [{"id": 9000 + team_id, "name": "Current Player"}],
        "modified_at": "2026-09-01T00:00:00Z",
        "dark_mode_image_url": "https://example.test/dark.png",
        "current_videogame": {"id": 4},
    }


def _player(player_id: int, name: str) -> dict[str, Any]:
    return {
        "id": player_id,
        "name": name,
        "first_name": " First ",
        "last_name": " Last ",
        "nationality": " ru ",
        "slug": f" {name.lower()} ",
        "active": True,
        "role": 4,
        "age": 25,
        "birthday": "2001-01-01",
        "modified_at": "2026-09-01T00:00:00Z",
        "current_team": {"id": 999},
        "image_url": "https://example.test/player.png",
        "current_videogame": {"id": 4},
    }


def _row() -> dict[str, Any]:
    team_a = _team(101, "Team A", " TEAM_SOURCE ", " cn ", " team-a ", " https://a.png ")
    team_b = _team(102, "Team B", "B", "us", "team-b", "https://b.png")
    team_c = _team(103, "Team C", "C", "se", "team-c", "https://c.png")
    roster_team_a = _team(
        101,
        "Roster Team A",
        " ROSTER_SOURCE ",
        " roster ",
        " roster-a ",
        " https://roster-a.png ",
    )
    roster_team_b = _team(102, "Roster Team B", "B", "us", "team-b", "https://b.png")
    roster_team_d = _team(104, "Team D", "D", " de ", " team-d ", " https://d.png ")

    return {
        "id": 21545,
        "serie_id": 10828,
        "league_id": 4106,
        "name": "Group Stage",
        "type": " group ",
        "country": None,
        "region": " world ",
        "begin_at": "2026-08-01T00:00:00Z",
        "end_at": "2026-08-15T00:00:00Z",
        "winner_id": 1669,
        "tier": " s ",
        "prizepool": " 1000000 ",
        "has_bracket": True,
        "slug": " group-stage ",
        "teams": [team_a, team_b, team_c],
        "expected_roster": [
            {"team": roster_team_a, "players": [_player(28009, "TORONTOTOKYO")]},
            {"team": roster_team_b, "players": [_player(28010, "Mira")]},
            {"team": roster_team_d, "players": [_player(28011, "Collapse")]},
        ],
        "matches": [{"id": 1638249}],
        "serie": {"id": 10828, "name": "The International 2026"},
        "league": {"id": 4106, "name": "The International"},
        "winner_type": "Team",
        "modified_at": "2026-09-01T00:00:00Z",
        "detailed_stats": True,
        "live_supported": True,
        "videogame": {"id": 4},
        "videogame_title": None,
    }


def test_tournament_mapping_compiles_all_criteria_into_one_request() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[], request=request)

    query = TournamentSearchInput(
        id=21545,
        series_id=10828,
        name="Group Stage",
        page=2,
        limit=50,
    )
    result = asyncio.run(_adapter(handler).search(query))

    assert result.items == []
    assert calls == [
        (
            "/dota2/tournaments",
            {
                "page": "2",
                "per_page": "50",
                "filter[id]": "21545",
                "filter[serie_id]": "10828",
                "search[name]": "Group Stage",
            },
        )
    ]


def test_tournament_normalization_projects_union_and_preserves_precedence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_row()], request=request)

    item = asyncio.run(_adapter(handler).search(TournamentSearchInput())).items[0]

    assert item.model_dump(mode="json") == {
        "id": 21545,
        "series_id": 10828,
        "league_id": 4106,
        "name": "Group Stage",
        "type": "group",
        "country": None,
        "region": "world",
        "begin_at": "2026-08-01T00:00:00Z",
        "end_at": "2026-08-15T00:00:00Z",
        "winner_id": 1669,
        "tier": "s",
        "prizepool": "1000000",
        "has_bracket": True,
        "slug": "group-stage",
        "participants": [
            {
                "team": {
                    "id": 101,
                    "name": "Team A",
                    "acronym": "TEAM_SOURCE",
                    "location": "cn",
                    "slug": "team-a",
                    "image_url": "https://a.png",
                },
                "expected_roster": [
                    {
                        "id": 28009,
                        "name": "TORONTOTOKYO",
                        "first_name": "First",
                        "last_name": "Last",
                        "nationality": "ru",
                        "slug": "torontotokyo",
                    }
                ],
            },
            {
                "team": {
                    "id": 102,
                    "name": "Team B",
                    "acronym": "B",
                    "location": "us",
                    "slug": "team-b",
                    "image_url": "https://b.png",
                },
                "expected_roster": [
                    {
                        "id": 28010,
                        "name": "Mira",
                        "first_name": "First",
                        "last_name": "Last",
                        "nationality": "ru",
                        "slug": "mira",
                    }
                ],
            },
            {
                "team": {
                    "id": 103,
                    "name": "Team C",
                    "acronym": "C",
                    "location": "se",
                    "slug": "team-c",
                    "image_url": "https://c.png",
                },
                "expected_roster": [],
            },
            {
                "team": {
                    "id": 104,
                    "name": "Team D",
                    "acronym": "D",
                    "location": "de",
                    "slug": "team-d",
                    "image_url": "https://d.png",
                },
                "expected_roster": [
                    {
                        "id": 28011,
                        "name": "Collapse",
                        "first_name": "First",
                        "last_name": "Last",
                        "nationality": "ru",
                        "slug": "collapse",
                    }
                ],
            },
        ],
    }


def test_tournament_collections_default_to_empty_lists() -> None:
    row = {
        "id": 21545,
        "serie_id": 10828,
        "league_id": 4106,
        "name": "Group Stage",
        "teams": None,
        "expected_roster": None,
    }

    item = PandaScoreTournamentAdapter._normalize(row)

    assert item.participants == []


def test_tournament_roster_has_partial_success() -> None:
    row = _row()
    row["expected_roster"][1]["players"] = [
        row["expected_roster"][1]["players"][0],
        {"id": 28012},
    ]
    anomalies = []

    item = PandaScoreTournamentAdapter._normalize(
        row,
        path="items[0]",
        anomalies=anomalies,
    )

    assert item.participants[1].team.id == 102
    assert [player.id for player in item.participants[1].expected_roster] == [28010]
    assert len(anomalies) == 1
    assert anomalies[0].path == "items[0].expected_roster[1].players[1]"
    assert anomalies[0].provider_id == 28012


def test_tournament_required_series_id_does_not_fallback_to_nested_serie() -> None:
    with pytest.raises(KeyError, match="serie_id"):
        PandaScoreTournamentAdapter._normalize(
            {
                "id": 21545,
                "league_id": 4106,
                "name": "Group Stage",
                "serie": {"id": 10828},
            }
        )
