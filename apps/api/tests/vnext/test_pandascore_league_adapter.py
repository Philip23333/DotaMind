from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.vnext.capabilities.esports.league import LeagueSearchInput
from app.vnext.providers.pandascore.client import PandaScoreClient
from app.vnext.providers.pandascore.league_adapter import PandaScoreLeagueAdapter


def _adapter(handler) -> PandaScoreLeagueAdapter:
    client = PandaScoreClient(
        base_url="https://api.pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    return PandaScoreLeagueAdapter(client)


def _row() -> dict[str, Any]:
    return {
        "id": 4106,
        "name": "The International",
        "slug": "dota-2-the-international",
        "image_url": "https://example.test/league.png",
        "modified_at": "2026-09-01T00:00:00Z",
    }


def test_name_mapping_uses_one_league_collection_request() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[_row()], request=request)

    result = asyncio.run(
        _adapter(handler).search(
            LeagueSearchInput(name="The International", page=1, limit=20)
        )
    )

    assert len(calls) == 1
    assert calls[0] == (
        "/dota2/leagues",
        {
            "search[name]": "The International",
            "page": "1",
            "per_page": "20",
        },
    )
    assert result.items[0].id == 4106


def test_id_mapping_uses_filter_and_pagination() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[_row()], request=request)

    asyncio.run(
        _adapter(handler).search(LeagueSearchInput(id=4106, page=2, limit=50))
    )

    assert calls == [
        (
            "/dota2/leagues",
            {
                "filter[id]": "4106",
                "page": "2",
                "per_page": "50",
            },
        )
    ]


def test_id_and_name_are_compiled_together() -> None:
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        return httpx.Response(200, json=[], request=request)

    asyncio.run(
        _adapter(handler).search(
            LeagueSearchInput(id=4106, name="The International")
        )
    )

    assert calls == [
        {
            "filter[id]": "4106",
            "search[name]": "The International",
            "page": "1",
            "per_page": "20",
        }
    ]


def test_normalization_exposes_only_id_and_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_row()], request=request)

    item = asyncio.run(_adapter(handler).search(LeagueSearchInput())).items[0]

    assert item.model_dump() == {"id": 4106, "name": "The International"}
    assert not hasattr(item, "slug")
    assert not hasattr(item, "image_url")
    assert not hasattr(item, "modified_at")
