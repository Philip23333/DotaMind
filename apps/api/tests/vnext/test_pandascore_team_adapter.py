from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.vnext.capabilities.esports.dtos import PlayerRole
from app.vnext.capabilities.esports.team import TeamSearchInput
from app.vnext.providers.pandascore.client import PandaScoreClient
from app.vnext.providers.pandascore.team_adapter import PandaScoreTeamAdapter


def _adapter(handler) -> PandaScoreTeamAdapter:
    client = PandaScoreClient(
        base_url="https://api.pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    return PandaScoreTeamAdapter(client)


def _row() -> dict[str, Any]:
    return {
        "id": 1647,
        "name": "Team Liquid",
        "acronym": "TL",
        "location": "NL",
        "slug": "team-liquid",
        "image_url": "https://example.test/liquid.png",
        "modified_at": "2026-09-01T00:00:00Z",
        "current_videogame": {"id": 4, "name": "Dota 2"},
        "players": [
            {
                "id": 27480,
                "name": "Larl",
                "active": True,
                "role": 2,
                "first_name": " Denis ",
                "last_name": " Sigitov ",
                "nationality": " ru ",
                "slug": " larl ",
                "image_url": " https://example.test/larl.png ",
                "modified_at": "2026-09-01T00:00:00Z",
                "current_team": {"id": 1647},
                "current_videogame": {"id": 4},
            },
            {
                "id": 99999,
                "name": "Mixed",
                "active": True,
                "role": " 1 / 2 ",
                "first_name": None,
                "last_name": None,
                "nationality": None,
                "slug": " mixed ",
                "image_url": " https://example.test/mixed.png ",
                "modified_at": "2026-09-01T00:00:00Z",
                "current_team": {"id": 1647},
                "current_videogame": {"id": 4},
            },
        ],
    }


def test_team_search_maps_all_semantic_fields_in_one_request() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[_row()], request=request)

    result = asyncio.run(
        _adapter(handler).search(
            TeamSearchInput(
                id=1647,
                name="Team Liquid",
                acronym="TL",
                page=2,
                limit=50,
            )
        )
    )

    assert calls == [
        (
            "/dota2/teams",
            {
                "page": "2",
                "per_page": "50",
                "filter[id]": "1647",
                "search[name]": "Team Liquid",
                "search[acronym]": "TL",
            },
        )
    ]
    assert result.page == 2
    assert result.limit == 50


def test_team_normalization_projects_current_roster_and_drops_provider_clutter() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_row()], request=request)

    item = asyncio.run(_adapter(handler).search(TeamSearchInput())).items[0]

    assert item.model_dump() == {
        "id": 1647,
        "name": "Team Liquid",
        "acronym": "TL",
        "location": "NL",
        "slug": "team-liquid",
        "image_url": "https://example.test/liquid.png",
        "current_roster": [
            {
                "id": 27480,
                "name": "Larl",
                "active": True,
                "role": (PlayerRole.mid,),
                "first_name": "Denis",
                "last_name": "Sigitov",
                "nationality": "ru",
                "slug": "larl",
                "image_url": "https://example.test/larl.png",
            },
            {
                "id": 99999,
                "name": "Mixed",
                "active": True,
                "role": (PlayerRole.carry, PlayerRole.mid),
                "first_name": None,
                "last_name": None,
                "nationality": None,
                "slug": "mixed",
                "image_url": "https://example.test/mixed.png",
            },
        ],
    }
    assert not hasattr(item, "modified_at")
    assert not hasattr(item, "current_videogame")


def test_player_role_mapping_supports_single_and_mixed_positions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert PandaScoreTeamAdapter._player_role(1) == (PlayerRole.carry,)
    assert PandaScoreTeamAdapter._player_role("1") == (PlayerRole.carry,)
    assert PandaScoreTeamAdapter._player_role(2) == (PlayerRole.mid,)
    assert PandaScoreTeamAdapter._player_role("1/2") == (
        PlayerRole.carry,
        PlayerRole.mid,
    )
    assert PandaScoreTeamAdapter._player_role(" 3 / 4 ") == (
        PlayerRole.offlane,
        PlayerRole.soft_support,
    )
    assert PandaScoreTeamAdapter._player_role(None) is None

    invalid_values = [0, 6, True, False, "", "carry", "mid", "1/6", "1/x"]
    with caplog.at_level("WARNING"):
        assert all(PandaScoreTeamAdapter._player_role(value) is None for value in invalid_values)
    for value in invalid_values:
        assert repr(value) in caplog.text


def test_team_current_roster_missing_players_defaults_to_empty() -> None:
    row = _row()
    row["players"] = None

    item = PandaScoreTeamAdapter._normalize(row)

    assert item.current_roster == []


def test_current_roster_active_is_required() -> None:
    row = _row()
    row["players"][0].pop("active")

    with pytest.raises(KeyError, match="active"):
        PandaScoreTeamAdapter._normalize(row)
