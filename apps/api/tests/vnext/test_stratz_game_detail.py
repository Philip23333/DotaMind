"""Internal STRATZ source boundary: identity, fidelity, reuse and safe failures."""

import asyncio
import copy
import json

import httpx
import pytest

from app.vnext.providers.source_reads import source_read_scope
from app.vnext.providers.stratz.client import StratzGraphQLClient
from app.vnext.providers.stratz.game_detail import StratzGameDetailAdapter
from app.vnext.tools.errors import StructuredToolError


def match_source():
    return {
        "id": 8960991322,
        "durationSeconds": 3862,
        "startDateTime": 1759800000,
        "didRadiantWin": False,
        "players": [
            {
                "steamAccountId": None,
                "playerSlot": 0,
                "kills": 0,
                "stats": {"extension": {"unknown": [None, False, 0]}},
                "playbackData": {"deathEvents": [], "inventoryEvents": []},
            }
        ],
    }


def adapter_for(handler):
    return StratzGameDetailAdapter(
        StratzGraphQLClient(
            graphql_url="https://stratz.test/graphql",
            token="private-token",
            transport=httpx.MockTransport(handler),
        )
    )


def test_internal_read_preserves_source_and_reuses_success_without_sharing_mutations():
    source = match_source()
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"data": {"match": source}})

    async def run():
        adapter = adapter_for(handler)
        with source_read_scope() as cache:
            first, second = await asyncio.gather(
                *[adapter.get_game_record(source["id"]) for _ in range(2)]
            )
            assert cache.remote_reads == 1 and cache.cache_hits == 1
            assert first.data == source == second.data
            first.data["players"][0]["stats"]["extension"] = None
            assert second.data == source
            assert first.retrieved_at.utcoffset() is not None
        assert calls[0]["variables"] == {"id": source["id"]}
        assert "goldEvents" in calls[0]["query"]
        assert "imp" not in calls[0]["query"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", 1),
        ("id", True),
        ("durationSeconds", -1),
        ("startDateTime", 10**30),
        ("didRadiantWin", 0),
        ("players", {}),
        ("pickBans", [False]),
        ("chatEvents", [{"time": "10"}]),
        ("players", [{"kills": True}]),
        ("players", [{"playbackData": {"deathEvents": [{"goldLost": "1"}]}}]),
        ("players", [{"playbackData": {"inventoryEvents": [{"item0": {"itemId": False}}]}}]),
        ("radiantTeam", {"id": 123, "name": "Team"}),
    ],
)
def test_rejects_mismatched_identity_and_malformed_known_fields(field, value):
    source = copy.deepcopy(match_source())
    source[field] = value
    adapter = adapter_for(lambda _: httpx.Response(200, json={"data": {"match": source}}))
    with pytest.raises(StructuredToolError) as exc:
        asyncio.run(adapter.get_game_record(8960991322))
    assert exc.value.code == "provider_schema_error"
    assert "private-token" not in str(exc.value)


@pytest.mark.parametrize(
    "response,code",
    [
        (httpx.Response(200, json={"data": {"match": None}}), "provider_error"),
        (httpx.Response(200, json={"data": {}}), "provider_schema_error"),
        (httpx.Response(200, json={"errors": [{"message": "private-token"}]}), "provider_error"),
        (httpx.Response(429, text="private-token"), "provider_http_error"),
    ],
)
def test_sanitized_failures_are_not_empty_successes(response, code):
    with pytest.raises(StructuredToolError) as exc:
        asyncio.run(adapter_for(lambda _: response).get_game_record(8960991322))
    assert exc.value.code == code
    assert "private-token" not in str(exc.value)


def test_timeout_cancellation_and_invalid_input():
    def timeout(_):
        raise httpx.ReadTimeout("private-token")

    with pytest.raises(StructuredToolError) as exc:
        asyncio.run(adapter_for(timeout).get_game_record(1))
    assert exc.value.code == "provider_timeout"

    def cancel(_):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(adapter_for(cancel).get_game_record(1))
    with pytest.raises(ValueError):
        asyncio.run(adapter_for(timeout).get_game_record(True))
