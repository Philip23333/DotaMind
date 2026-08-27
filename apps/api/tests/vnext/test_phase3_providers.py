from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.vnext.providers.pandascore.adapter import PandaScoreAdapter
from app.vnext.providers.pandascore.models import PandaScorePlayer, PandaScoreTeam
from tests.vnext.phase2_support import load_fixture


def _json_response(request: httpx.Request, payload: Any) -> httpx.Response:
    return httpx.Response(200, json=payload, request=request)


def test_pandascore_adapter_fetches_team_and_player_capability_routes() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/dota2/teams":
            return _json_response(request, load_fixture("pandascore", "teams_search.json"))
        if request.url.path == "/teams/1669":
            return _json_response(request, load_fixture("pandascore", "team_detail.json"))
        if request.url.path == "/dota2/players":
            return _json_response(request, load_fixture("pandascore", "players_search.json"))
        if request.url.path == "/players/30258":
            return _json_response(request, load_fixture("pandascore", "player_detail.json"))
        raise AssertionError(request.url)

    async def exercise() -> tuple[Any, Any, Any, Any]:
        adapter = PandaScoreAdapter(
            base_url="https://pandascore.test",
            token="test-token",
            transport=httpx.MockTransport(handler),
        )
        teams = await adapter.search_teams(query="Team Spirit", limit=7)
        team = await adapter.get_team(1669)
        players = await adapter.search_players(query="Yatoro", limit=7)
        player = await adapter.get_player(30258)
        await adapter.aclose()
        return teams, team, players, player

    teams, team, players, player = asyncio.run(exercise())

    assert isinstance(teams.items[0], PandaScoreTeam)
    assert teams.items[0].provider_id == 1669
    assert team.item.name == "Team Spirit"
    assert len(team.item.players) == 2
    assert team.item.players[0].birthday is not None
    assert isinstance(players.items[0], PandaScorePlayer)
    assert [item.provider_id for item in players.items] == [54603, 30258]
    assert player.item.provider_id == 30258
    assert player.item.current_team is not None
    assert player.item.current_team.provider_id == 1669

    assert [request.url.path for request in seen] == [
        "/dota2/teams",
        "/teams/1669",
        "/dota2/players",
        "/players/30258",
    ]
    assert seen[0].url.params["search[name]"] == "Team Spirit"
    assert seen[2].url.params["search[name]"] == "Yatoro"
    assert all(request.headers["authorization"] == "Bearer test-token" for request in seen)
    assert all("test-token" not in str(request.url) for request in seen)


def test_pandascore_player_model_preserves_nullable_source_facts_and_home_town_alias() -> None:
    player = PandaScorePlayer.model_validate(
        {
            "id": 9001,
            "name": "Example",
            "age": 23,
            "birthday": None,
            "birth_year": None,
            "home_town": "Kyiv",
            "current_team": None,
        }
    )

    assert player.birthday is None
    assert player.birth_year is None
    assert player.hometown == "Kyiv"
    assert player.current_team is None
    assert "age" not in player.model_dump()
