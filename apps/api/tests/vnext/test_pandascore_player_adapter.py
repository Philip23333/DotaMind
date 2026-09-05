from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.vnext.capabilities.esports.player import PlayerSearchInput
from app.vnext.providers.pandascore.client import PandaScoreClient
from app.vnext.providers.pandascore.player_adapter import PandaScorePlayerAdapter


def _adapter(handler) -> PandaScorePlayerAdapter:
    client = PandaScoreClient(
        base_url="https://api.pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    return PandaScorePlayerAdapter(client)


def _row(*, current_team: Any = None) -> dict[str, Any]:
    return {
        "id": 1669,
        "name": "Ame",
        "first_name": "Wang",
        "last_name": "Chunyu",
        "active": True,
        "nationality": "CN",
        "role": "carry",
        "current_team": current_team,
        "slug": "ame",
        "image_url": "https://example.test/ame.png",
        "modified_at": "2026-09-01T00:00:00Z",
        "birthday": "2000-01-01",
        "current_videogame": {"id": 4, "name": "Dota 2"},
    }


def test_player_search_maps_all_semantic_fields_in_one_request() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        return httpx.Response(
            200,
            json=[
                _row(
                    current_team={
                        "id": 1647,
                        "name": "Team Liquid",
                        "acronym": "TL",
                        "slug": "team-liquid",
                        "image_url": "https://example.test/liquid.png",
                        "modified_at": "2026-09-01T00:00:00Z",
                    }
                )
            ],
            request=request,
        )

    result = asyncio.run(
        _adapter(handler).search(
            PlayerSearchInput(
                id=1669,
                team_id=1647,
                name="Ame",
                first_name="Wang",
                last_name="Chunyu",
                active=True,
                page=2,
                limit=50,
            )
        )
    )

    assert calls == [
        (
            "/dota2/players",
            {
                "page": "2",
                "per_page": "50",
                "filter[id]": "1669",
                "filter[team_id]": "1647",
                "filter[active]": "true",
                "search[name]": "Ame",
                "search[first_name]": "Wang",
                "search[last_name]": "Chunyu",
            },
        )
    ]
    assert result.page == 2
    assert result.limit == 50


def test_player_normalization_keeps_current_team_summary() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                _row(
                    current_team={
                        "id": 1647,
                        "name": "Team Liquid",
                        "acronym": "TL",
                        "slug": "team-liquid",
                    }
                )
            ],
            request=request,
        )

    item = asyncio.run(_adapter(handler).search(PlayerSearchInput())).items[0]

    assert item.model_dump() == {
        "id": 1669,
        "name": "Ame",
        "first_name": "Wang",
        "last_name": "Chunyu",
        "active": True,
        "nationality": "CN",
        "role": "carry",
        "current_team": {"id": 1647, "name": "Team Liquid", "acronym": "TL"},
    }
    assert not hasattr(item, "slug")
    assert not hasattr(item, "image_url")
    assert not hasattr(item, "modified_at")
    assert not hasattr(item, "birthday")
    assert not hasattr(item, "current_videogame")


def test_player_without_current_team_is_valid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_row()], request=request)

    item = asyncio.run(_adapter(handler).search(PlayerSearchInput())).items[0]

    assert item.current_team is None
