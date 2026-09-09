from __future__ import annotations

import asyncio

import httpx
import pytest

from app.vnext.providers.pandascore.client import (
    PandaScoreClient,
    PandaScoreProtocolError,
)


def _client(handler) -> PandaScoreClient:
    return PandaScoreClient(
        base_url="https://api.pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )


def test_get_object_returns_json_object_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/tournaments/14384/rosters"
        return httpx.Response(
            200,
            json={"rosters": [], "type": "Team"},
            request=request,
        )

    result = asyncio.run(_client(handler).get_object("/tournaments/14384/rosters"))

    assert result == {"rosters": [], "type": "Team"}


def test_get_object_rejects_non_object_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[], request=request)

    with pytest.raises(PandaScoreProtocolError, match="expected object response"):
        asyncio.run(_client(handler).get_object("/tournaments/14384/rosters"))


def test_get_list_preserves_malformed_items_for_adapter_mapping() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": 1}, "bad-row", {"id": 2}], request=request)

    assert asyncio.run(_client(handler).get_list("/dota2/teams", params={})) == [
        {"id": 1},
        "bad-row",
        {"id": 2},
    ]


def test_get_list_rejects_non_collection_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": []}, request=request)

    with pytest.raises(PandaScoreProtocolError, match="JSON list"):
        asyncio.run(_client(handler).get_list("/dota2/teams", params={}))
