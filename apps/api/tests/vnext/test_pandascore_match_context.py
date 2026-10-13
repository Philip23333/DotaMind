from __future__ import annotations

import asyncio
import copy
from typing import Any

import httpx
import pytest

from app.vnext.providers.pandascore import PandaScoreMatchContextAdapter
from app.vnext.providers.pandascore.client import PandaScoreClient
from app.vnext.tools.errors import StructuredToolError


def _context(match_id: int = 42) -> dict[str, Any]:
    team = {
        "id": 10,
        "name": "Alpha",
        "acronym": "ALP",
        "image_url": "https://cdn.example/alpha.png",
        "future_team_fact": {"kept": True},
    }
    return {
        "id": match_id,
        "name": "Grand Final",
        "status": "finished",
        "match_type": "best_of",
        "number_of_games": 3,
        "league_id": 1,
        "serie_id": 2,
        "tournament_id": 3,
        "begin_at": "2026-09-01T10:00:00Z",
        "end_at": "2026-09-01T12:00:00Z",
        "scheduled_at": "2026-09-01T10:00:00Z",
        "original_scheduled_at": "2026-09-01T09:30:00Z",
        "league": {"id": 1, "name": "League", "future": [1, None]},
        "serie": {
            "id": 2,
            "name": "Edition",
            "year": 2026,
            "season": None,
        },
        "tournament": {"id": 3, "name": "Group Stage"},
        "opponents": [
            {"opponent": team},
            {"opponent": None},
        ],
        "results": [
            {"team_id": 10, "score": 0},
            {"team_id": 11, "score": None},
        ],
        "winner_id": None,
        "winner": None,
        "games": [
            {
                "id": 9001,
                "position": 2,
                "status": "finished",
                "begin_at": "2026-09-01T10:05:00Z",
                "end_at": "2026-09-01T10:45:00Z",
                "length": 2400,
                "winner_id": 10,
                "complete": True,
                "forfeit": False,
                "match_id": match_id,
                "unknown_game_fact": {"flag": False, "value": 0},
            }
        ],
        "draw": False,
        "forfeit": False,
        "rescheduled": False,
        "future_match_fact": {"ordered": ["a", "b"], "null": None},
    }


def _client(
    handler: Any,
    *,
    token: str = "test-secret-token",
    base_url: str = "https://api.pandascore.test",
) -> tuple[PandaScoreClient, httpx.MockTransport]:
    transport = httpx.MockTransport(handler)
    return (
        PandaScoreClient(
            base_url=base_url,
            token=token,
            timeout_seconds=3.5,
            transport=transport,
        ),
        transport,
    )


def _get(adapter: PandaScoreMatchContextAdapter, match_id: Any = 42) -> Any:
    return asyncio.run(adapter.get_match_context(match_id))


def _schema_error(exc: StructuredToolError, path: str) -> None:
    assert exc.code == "provider_schema_error"
    assert exc.details == {"provider": "pandascore", "path": path}


def test_exact_match_query_uses_one_bounded_collection_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[_context()], request=request)

    client, _ = _client(handler)
    result = _get(PandaScoreMatchContextAdapter(client))

    assert result == _context()
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.path == "/dota2/matches"
    assert dict(request.url.params) == {
        "filter[id]": "42",
        "page": "1",
        "per_page": "2",
    }
    assert request.headers["Authorization"] == "Bearer test-secret-token"
    assert request.headers["Accept"] == "application/json"


@pytest.mark.parametrize("match_id", [True, False, "42", 42.0, None, 0, -1])
def test_invalid_id_fails_before_request(match_id: Any) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[], request=request)

    client, _ = _client(handler)
    with pytest.raises(ValueError, match="positive integer"):
        _get(PandaScoreMatchContextAdapter(client), match_id)
    assert requests == []


def test_empty_exact_query_returns_none() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json=[], request=request)

    client, _ = _client(handler)
    assert _get(PandaScoreMatchContextAdapter(client)) is None
    assert requests == 1


@pytest.mark.parametrize(
    "rows",
    [
        [_context(), _context()],
        [_context(), {**_context(), "id": 43}],
    ],
    ids=["duplicate-id", "different-id"],
)
def test_multiple_rows_fail_instead_of_selecting_first(rows: list[dict[str, Any]]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows, request=request)

    client, _ = _client(handler)
    with pytest.raises(StructuredToolError) as error:
        _get(PandaScoreMatchContextAdapter(client))
    _schema_error(error.value, "response")


def test_identity_mismatch_and_non_object_records_fail() -> None:
    for rows, path in [
        ([{**_context(), "id": 43}], "response[0].id"),
        (["not-an-object"], "response[0]"),
    ]:
        def handler(request: httpx.Request, payload: Any = rows) -> httpx.Response:
            return httpx.Response(200, json=payload, request=request)

        client, _ = _client(handler)
        with pytest.raises(StructuredToolError) as error:
            _get(PandaScoreMatchContextAdapter(client))
        _schema_error(error.value, path)


def test_full_source_context_and_optional_states_are_preserved() -> None:
    source = _context()
    source["games"][0]["position"] = 4
    source["games"][0]["length"] = 0
    source["games"][0]["winner"] = {"id": 10, "type": "Team", "extra": "x"}
    source["winner"] = {"id": 10, "name": "Alpha", "type": "Team"}
    source["winner_type"] = "Team"
    source["results"].reverse()
    original = copy.deepcopy(source)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[source], request=request)

    client, _ = _client(handler)
    result = _get(PandaScoreMatchContextAdapter(client))

    assert result == original
    assert result is not source
    assert result["games"][0]["position"] == 4
    assert result["games"][0]["length"] == 0
    assert result["results"][0]["score"] is None
    assert result["draw"] is False
    assert result["future_match_fact"] == original["future_match_fact"]


def test_tbd_match_and_unstarted_game_are_valid() -> None:
    row = _context()
    row.update(
        {
            "begin_at": None,
            "end_at": None,
            "winner_id": None,
            "winner": None,
            "opponents": [{"opponent": None}],
            "results": [],
            "games": [
                {
                    "id": 9002,
                    "position": 1,
                    "status": "not_started",
                    "begin_at": None,
                    "end_at": None,
                    "length": None,
                    "winner": None,
                    "winner_type": None,
                    "complete": False,
                    "finished": False,
                    "forfeit": False,
                }
            ],
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[row], request=request)

    client, _ = _client(handler)
    assert _get(PandaScoreMatchContextAdapter(client)) == row


@pytest.mark.parametrize("games_state", ["missing", "null", "empty"])
def test_missing_and_nullable_context_relations_are_preserved(games_state: str) -> None:
    row = _context()
    row.pop("league")
    row["serie"] = None
    row["tournament"] = {}
    row.pop("opponents")
    row["results"] = None
    if games_state == "missing":
        row.pop("games")
    elif games_state == "null":
        row["games"] = None
    else:
        row["games"] = []
    original = copy.deepcopy(row)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[row], request=request)

    client, _ = _client(handler)
    assert _get(PandaScoreMatchContextAdapter(client)) == original


def test_conflicting_match_time_and_game_length_are_preserved() -> None:
    row = _context()
    row["games"][0].update(
        {
            "begin_at": "2026-09-01T10:00:00Z",
            "end_at": "2026-09-01T10:00:03Z",
            "length": 1907,
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[row], request=request)

    client, _ = _client(handler)
    assert _get(PandaScoreMatchContextAdapter(client)) == row


@pytest.mark.parametrize(
    ("mutate", "path"),
    [
        (lambda row: row.pop("id"), "response[0].id"),
        (lambda row: row.update(id=True), "response[0].id"),
        (lambda row: row.update(league_id=False), "response[0].league_id"),
        (lambda row: row.update(status=1), "response[0].status"),
        (lambda row: row.update(begin_at="not-a-date"), "response[0].begin_at"),
        (lambda row: row.update(league=[]), "response[0].league"),
        (lambda row: row.update(serie={"year": "2026"}), "response[0].serie.year"),
        (
            lambda row: row.update(opponents=[{"opponent": "unknown"}]),
            "response[0].opponents[0].opponent",
        ),
        (
            lambda row: row.update(results={"team_id": 10}),
            "response[0].results",
        ),
        (
            lambda row: row.update(results=[{"team_id": 10, "score": True}]),
            "response[0].results[0].score",
        ),
        (
            lambda row: row.update(opponents=[{"opponent": {"id": True}}]),
            "response[0].opponents[0].opponent.id",
        ),
        (
            lambda row: row.update(games=[{"id": True, "position": 1}]),
            "response[0].games[0].id",
        ),
        (
            lambda row: row.update(games=[{"id": 9, "position": False}]),
            "response[0].games[0].position",
        ),
        (
            lambda row: row["games"][0].update(match_id=99),
            "response[0].games[0].match_id",
        ),
        (
            lambda row: row["games"][0].update(complete=1),
            "response[0].games[0].complete",
        ),
    ],
)
def test_invalid_known_nested_fields_fail_the_complete_match(
    mutate: Any,
    path: str,
) -> None:
    row = _context()
    mutate(row)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[row], request=request)

    client, _ = _client(handler)
    with pytest.raises(StructuredToolError) as error:
        _get(PandaScoreMatchContextAdapter(client))
    _schema_error(error.value, path)


def test_non_finite_nested_json_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'[{"id":42,"future":{"value":NaN}}]',
            headers={"Content-Type": "application/json"},
            request=request,
        )

    client, _ = _client(handler)
    with pytest.raises(StructuredToolError) as error:
        _get(PandaScoreMatchContextAdapter(client))
    _schema_error(error.value, "response[0].future.value")


def test_non_collection_and_non_json_responses_are_schema_errors() -> None:
    for is_json_object in (True, False):
        def handler(
            request: httpx.Request,
            json_object: bool = is_json_object,
        ) -> httpx.Response:
            if json_object:
                return httpx.Response(200, json={"id": 42}, request=request)
            return httpx.Response(200, content=b"not-json", request=request)

        client, _ = _client(handler)
        with pytest.raises(StructuredToolError) as error:
            _get(PandaScoreMatchContextAdapter(client))
        _schema_error(error.value, "response")


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
def test_http_errors_are_sanitized_and_not_retried(status: int, category: str) -> None:
    requests = 0
    secret_body = "provider-private-error-body"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(status, content=secret_body.encode(), request=request)

    client, _ = _client(handler)
    with pytest.raises(StructuredToolError) as error:
        _get(PandaScoreMatchContextAdapter(client))

    assert error.value.code == "provider_http_error"
    assert error.value.details == {
        "provider": "pandascore",
        "status_code": status,
        "category": category,
    }
    assert secret_body not in str(error.value)
    assert "test-secret-token" not in str(error.value)
    assert "pandascore.test" not in str(error.value)
    assert requests == 1


def test_timeout_transport_and_missing_token_have_distinct_failures() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout detail", request=request)

    client, _ = _client(timeout_handler)
    with pytest.raises(StructuredToolError) as timeout_error:
        _get(PandaScoreMatchContextAdapter(client))
    assert timeout_error.value.code == "provider_timeout"
    assert timeout_error.value.details == {"provider": "pandascore"}
    assert "private timeout detail" not in str(timeout_error.value)

    def transport_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private transport detail", request=request)

    client, _ = _client(transport_handler)
    with pytest.raises(StructuredToolError) as transport_error:
        _get(PandaScoreMatchContextAdapter(client))
    assert transport_error.value.code == "provider_error"
    assert transport_error.value.details == {
        "provider": "pandascore",
        "category": "transport_error",
    }
    assert "private transport detail" not in str(transport_error.value)

    calls = 0

    def no_token_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[], request=request)

    client, _ = _client(no_token_handler, token="")
    with pytest.raises(StructuredToolError) as config_error:
        _get(PandaScoreMatchContextAdapter(client))
    assert config_error.value.code == "configuration_error"
    assert config_error.value.details == {"provider": "pandascore"}
    assert calls == 0


def test_cancelled_request_propagates_and_closes_transport() -> None:
    entered = asyncio.Event()
    never = asyncio.Event()

    class TrackingTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.closed = False

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            entered.set()
            await never.wait()
            return httpx.Response(200, json=[], request=request)

        async def aclose(self) -> None:
            self.closed = True

    async def scenario() -> tuple[asyncio.CancelledError, TrackingTransport]:
        transport = TrackingTransport()
        client = PandaScoreClient(
            base_url="https://api.pandascore.test",
            token="test-secret-token",
            transport=transport,
        )
        task = asyncio.create_task(
            PandaScoreMatchContextAdapter(client).get_match_context(42)
        )
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await asyncio.wait_for(task, timeout=1)
        return cancelled.value, transport

    error, transport = asyncio.run(scenario())
    assert isinstance(error, asyncio.CancelledError)
    assert transport.closed is True
