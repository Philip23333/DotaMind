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


@pytest.mark.parametrize("match_id", [1, 739594, 9018736585])
def test_empty_record_error_is_scoped_to_requested_id_without_digit_heuristics(match_id):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content)["variables"])
        return httpx.Response(200, json={"data": {"match": None}})

    with pytest.raises(StructuredToolError) as caught:
        asyncio.run(adapter_for(handler).get_game_record(match_id))
    assert calls == [{"id": match_id}]
    assert caught.value.code == "provider_error"
    assert str(caught.value) == "STRATZ returned no record for the requested Valve game ID"
    assert caught.value.details == {"provider": "stratz", "valve_game_id": match_id}


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


def test_optional_playback_graphql_errors_keep_valid_primary_facts_with_safe_paths():
    source = match_source()
    source["players"][0]["playbackData"] = None
    response = {
        "data": {"match": source},
        "errors": [{"message": "private-token", "path": ["match", "players", 0, "playbackData"]}],
    }
    record = asyncio.run(
        adapter_for(lambda _: httpx.Response(200, json=response)).get_game_record(source["id"])
    )
    assert record.data["durationSeconds"] == 3862
    assert record.field_issues == ["players[0].playbackData"]
    assert "private-token" not in record.model_dump_json()


@pytest.mark.parametrize(
    "path",
    [
        None,
        ["match"],
        ["match", "id"],
        ["match", "players", 0, "kills"],
        ["match", "players", -1, "playbackData"],
        ["match", "players", True, "playbackData"],
        ["match", "players", 100, "playbackData"],
    ],
)
def test_partial_graphql_support_does_not_accept_root_identity_or_unknown_errors(path):
    source = match_source()
    response = {"data": {"match": source}, "errors": [{"message": "private-token", "path": path}]}
    with pytest.raises(StructuredToolError) as caught:
        asyncio.run(
            adapter_for(lambda _: httpx.Response(200, json=response)).get_game_record(source["id"])
        )
    assert caught.value.code == "provider_error"
