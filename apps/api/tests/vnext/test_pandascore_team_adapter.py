from __future__ import annotations

import asyncio
from typing import Any

import httpx

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
        "players": [{"id": 1, "name": "Example"}],
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


def test_team_normalization_keeps_identity_fields_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_row()], request=request)

    item = asyncio.run(_adapter(handler).search(TeamSearchInput())).items[0]

    assert item.model_dump() == {
        "id": 1647,
        "name": "Team Liquid",
        "acronym": "TL",
        "location": "NL",
    }
    assert not hasattr(item, "players")
    assert not hasattr(item, "slug")
    assert not hasattr(item, "image_url")
    assert not hasattr(item, "modified_at")
    assert not hasattr(item, "current_videogame")
