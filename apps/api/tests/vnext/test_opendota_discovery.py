from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.vnext.providers.opendota import OpenDotaClient, OpenDotaDiscoveryAdapter
from app.vnext.tools.errors import StructuredToolError

_KEY = "fixture-opendota-secret"
_LEAGUE_ID = 20359


def _run(awaitable):
    return asyncio.run(awaitable)


def _adapter(handler, *, key: str = _KEY, base_url: str = "https://api.example/api"):
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = OpenDotaClient(
        base_url=base_url,
        api_key=key,
        timeout_seconds=2.75,
        transport=httpx.MockTransport(recording_handler),
    )
    return OpenDotaDiscoveryAdapter(client), client, requests


def _league(league_id: int = 1, **overrides: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "leagueid": league_id,
        "name": "Example League",
        "tier": "professional",
        "extension": {"nested": [0, False, None]},
    }
    result.update(overrides)
    return result


def _league_match(match_id: int = 100, **overrides: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "match_id": match_id,
        "start_time": 0,
        "duration": 0,
        "radiant_team_id": 0,
        "dire_team_id": None,
        "radiant_name": "Radiant team",
        "dire_name": None,
        "radiant_win": False,
        "leagueid": _LEAGUE_ID,
        "series_id": 0,
        "series_type": 0,
        "extension": {"unknown": [None, 0, False]},
    }
    result.update(overrides)
    return result


def test_fixed_collection_endpoints_use_one_request_and_preserve_base_path() -> None:
    rows_by_path = {
        "/root/api/leagues": [_league(1), _league(2)],
        f"/root/api/leagues/{_LEAGUE_ID}/matches": [_league_match()],
    }
    adapter, client, requests = _adapter(
        lambda request: httpx.Response(200, json=rows_by_path[request.url.path], request=request),
        base_url="https://api.example/root/api/",
    )

    async def scenario() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        leagues = await adapter.get_leagues()
        matches = await adapter.get_league_matches(_LEAGUE_ID)
        return leagues, matches

    leagues, matches = _run(scenario())

    assert [row["leagueid"] for row in leagues] == [1, 2]
    assert matches[0]["match_id"] == 100
    assert [request.url.path for request in requests] == list(rows_by_path)
    assert all(request.url.params.get("api_key") == _KEY for request in requests)
    assert all(len(request.url.params) == 1 for request in requests)
    assert len(requests) == 2
    assert client.timeout_seconds == 2.75
    assert _KEY not in repr(client)


def test_league_and_match_collections_preserve_order_and_complete_source_fields() -> None:
    league_rows = [
        _league(8, tier=None, leagueid=8),
        _league(3, name="", leagueid=3),
    ]
    match_rows = [
        _league_match(201, radiant_team_name="Radiant", dire_team_name="Dire"),
        {"match_id": 202, "leagueid": _LEAGUE_ID, "series_id": 17},
        _league_match(203, series_id=None, radiant_win=None),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        rows = league_rows if request.url.path.endswith("/leagues") else match_rows
        return httpx.Response(200, json=rows, request=request)

    adapter, _, _ = _adapter(handler)
    result_leagues = _run(adapter.get_leagues())
    result_matches = _run(adapter.get_league_matches(_LEAGUE_ID))

    assert result_leagues == league_rows
    assert result_matches == match_rows
    assert [row["match_id"] for row in result_matches] == [201, 202, 203]
    assert result_matches[0]["series_id"] == 0
    assert result_matches[1] == {
        "match_id": 202,
        "leagueid": _LEAGUE_ID,
        "series_id": 17,
    }
    assert "dire_team_id" not in result_matches[1]
    assert result_matches[2]["series_id"] is None
    assert result_matches[2]["radiant_win"] is None


@pytest.mark.parametrize("payload", [[], [_league(1)], [_league(2)]])
def test_valid_league_collection_and_empty_collection(payload) -> None:
    adapter, _, requests = _adapter(
        lambda request: httpx.Response(200, json=payload, request=request)
    )

    assert _run(adapter.get_leagues()) == payload
    assert len(requests) == 1


@pytest.mark.parametrize("payload", [[], [_league_match(1)], [_league_match(2)]])
def test_valid_match_collection_accepts_empty_and_varied_series_ids(payload) -> None:
    adapter, _, requests = _adapter(
        lambda request: httpx.Response(200, json=payload, request=request)
    )

    assert _run(adapter.get_league_matches(_LEAGUE_ID)) == payload
    assert len(requests) == 1


@pytest.mark.parametrize("league_id", [True, False, "20359", 20359.0, None, 0, -1])
def test_invalid_league_id_fails_before_provider_request(league_id) -> None:
    adapter, _, requests = _adapter(
        lambda request: httpx.Response(200, json=[], request=request)
    )

    with pytest.raises(ValueError, match="positive integer"):
        _run(adapter.get_league_matches(league_id))
    assert requests == []


@pytest.mark.parametrize(
    ("payload", "path"),
    [
        ({"error": "private provider error"}, "response"),
        (None, "response"),
        ([None], "response[0]"),
        ([{"leagueid": True, "name": "League"}], "response[0].leagueid"),
        ([{"leagueid": 0, "name": "League"}], "response[0].leagueid"),
        ([{"leagueid": 1, "name": None}], "response[0].name"),
    ],
)
def test_invalid_league_collection_fails_with_source_path(payload, path: str) -> None:
    adapter, _, _ = _adapter(
        lambda request: httpx.Response(200, json=payload, request=request)
    )

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_leagues())

    assert raised.value.code == "provider_schema_error"
    assert raised.value.details == {"provider": "opendota", "path": path}
    assert "private provider error" not in str(raised.value)


@pytest.mark.parametrize(
    ("changes", "path"),
    [
        ({"match_id": True}, "match_id"),
        ({"match_id": "100"}, "match_id"),
        ({"match_id": 0}, "match_id"),
        ({"start_time": False}, "start_time"),
        ({"duration": "20"}, "duration"),
        ({"radiant_team_id": 1.5}, "radiant_team_id"),
        ({"dire_team_id": "3"}, "dire_team_id"),
        ({"radiant_name": 12}, "radiant_name"),
        ({"dire_team_name": False}, "dire_team_name"),
        ({"radiant_win": 0}, "radiant_win"),
        ({"leagueid": "20359"}, "leagueid"),
        ({"series_id": False}, "series_id"),
        ({"series_type": 1.0}, "series_type"),
    ],
)
def test_invalid_match_fields_fail_the_entire_collection(changes, path: str) -> None:
    invalid = _league_match(2)
    invalid.update(changes)
    payload = [_league_match(1), invalid]
    adapter, _, _ = _adapter(
        lambda request: httpx.Response(200, json=payload, request=request)
    )

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_league_matches(_LEAGUE_ID))

    assert raised.value.code == "provider_schema_error"
    assert raised.value.details["path"] == f"response[1].{path}"


@pytest.mark.parametrize(
    "payload",
    [{"error": "not a collection"}, {"match_id": 1}, 4, "[]", ["bad"]],
)
def test_invalid_match_collection_shape_is_not_an_empty_success(payload) -> None:
    adapter, _, _ = _adapter(
        lambda request: httpx.Response(200, json=payload, request=request)
    )

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_league_matches(_LEAGUE_ID))

    assert raised.value.code == "provider_schema_error"
    assert raised.value.details["path"] in {"response", "response[0]"}


def test_non_finite_json_constant_is_rejected_as_schema_error() -> None:
    adapter, _, _ = _adapter(
        lambda request: httpx.Response(
            200,
            content=b'[{"match_id":100,"extension":{"value":NaN}}]',
            headers={"Content-Type": "application/json"},
            request=request,
        )
    )

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_league_matches(_LEAGUE_ID))

    assert raised.value.code == "provider_schema_error"
    assert raised.value.details["path"] == "response[0].extension.value"


def test_non_finite_nested_league_value_is_rejected() -> None:
    adapter, _, _ = _adapter(
        lambda request: httpx.Response(
            200,
            content=b'[{"leagueid":1,"name":"League","extension":[Infinity]}]',
            headers={"Content-Type": "application/json"},
            request=request,
        )
    )

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_leagues())

    assert raised.value.code == "provider_schema_error"
    assert raised.value.details["path"] == "response[0].extension[0]"


def test_non_matching_league_id_is_rejected_without_returning_partial_rows() -> None:
    adapter, _, _ = _adapter(
        lambda request: httpx.Response(
            200,
            json=[_league_match(1), _league_match(2, leagueid=_LEAGUE_ID + 1)],
            request=request,
        )
    )

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_league_matches(_LEAGUE_ID))

    assert raised.value.code == "provider_schema_error"
    assert raised.value.details["path"] == "response[1].leagueid"


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, "authentication_or_access"),
        (403, "authentication_or_access"),
        (404, "not_found_or_unavailable"),
        (429, "rate_limited"),
        (500, "upstream_error"),
    ],
)
def test_http_failures_are_structured_sanitized_and_not_retried(status: int, category: str) -> None:
    adapter, client, requests = _adapter(
        lambda request: httpx.Response(status, text=f"private {_KEY}", request=request)
    )

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_leagues())

    assert raised.value.code == "provider_http_error"
    assert raised.value.details == {
        "provider": "opendota",
        "status_code": status,
        "category": category,
    }
    assert _KEY not in str(raised.value)
    assert _KEY not in repr(client)
    assert len(requests) == 1


def test_timeout_transport_and_non_json_failures_keep_existing_error_semantics() -> None:
    timeout_adapter, _, timeout_requests = _adapter(
        lambda request: (_ for _ in ()).throw(
            httpx.ReadTimeout(f"secret {_KEY} at {request.url}", request=request)
        )
    )
    with pytest.raises(StructuredToolError) as timeout:
        _run(timeout_adapter.get_leagues())
    assert timeout.value.code == "provider_timeout"
    assert _KEY not in str(timeout.value)
    assert len(timeout_requests) == 1

    transport_adapter, _, transport_requests = _adapter(
        lambda request: (_ for _ in ()).throw(
            httpx.ConnectError(f"secret {_KEY} at {request.url}", request=request)
        )
    )
    with pytest.raises(StructuredToolError) as transport:
        _run(transport_adapter.get_leagues())
    assert transport.value.code == "provider_error"
    assert _KEY not in str(transport.value)
    assert len(transport_requests) == 1

    non_json_adapter, _, _ = _adapter(
        lambda request: httpx.Response(
            200,
            text=f"not json {_KEY}",
            headers={"Content-Type": "text/plain"},
            request=request,
        )
    )
    with pytest.raises(StructuredToolError) as non_json:
        _run(non_json_adapter.get_leagues())
    assert non_json.value.code == "provider_schema_error"
    assert non_json.value.details == {"provider": "opendota", "path": "response"}
    assert _KEY not in str(non_json.value)


def test_cancellation_propagates_and_closes_transport() -> None:
    class BlockingTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.exited = asyncio.Event()
            self.closed = False

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.exited.set()

        async def aclose(self) -> None:
            self.closed = True

    async def scenario() -> None:
        transport = BlockingTransport()
        adapter = OpenDotaDiscoveryAdapter(OpenDotaClient(transport=transport))
        task = asyncio.create_task(adapter.get_leagues())
        await asyncio.wait_for(transport.started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert transport.exited.is_set()
        assert transport.closed

    _run(asyncio.wait_for(scenario(), timeout=2))
