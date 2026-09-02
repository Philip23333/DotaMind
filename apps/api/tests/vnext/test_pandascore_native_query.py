from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.vnext.providers.pandascore.adapter import PandaScoreAdapter, PandaScoreSchemaError
from app.vnext.providers.pandascore.capabilities import (
    EsportsSearchQuery,
    PandaScoreCapabilities,
    PandaScoreQueryValidationError,
)
from app.vnext.providers.pandascore.query import (
    PandaScoreNativeQueryExecutor,
    compile_query,
)


def _compiled(query: EsportsSearchQuery | dict[str, Any]):
    capabilities = PandaScoreCapabilities.load()
    normalized_query = capabilities.validate_query(query)
    endpoint = capabilities.endpoint(normalized_query.resource, normalized_query.scope)
    return compile_query(normalized_query, endpoint)


def _executor(handler) -> tuple[PandaScoreNativeQueryExecutor, PandaScoreAdapter]:
    adapter = PandaScoreAdapter(
        base_url="https://pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    return PandaScoreNativeQueryExecutor(PandaScoreCapabilities.load(), adapter), adapter


def test_compiler_selects_endpoint_paths_and_native_parameter_names() -> None:
    league = _compiled(
        EsportsSearchQuery(resource="league", search={"name": "The International"}, page_size=5)
    )
    assert league.path == "/dota2/leagues"
    assert league.params == {
        "page[number]": 1,
        "page[size]": 5,
        "search[name]": "The International",
    }

    serie = _compiled({"resource": "serie", "filter": {"league_id": 4106, "year": 2026}})
    assert serie.path == "/dota2/series"
    assert serie.params["filter[league_id]"] == 4106
    assert serie.params["filter[year]"] == 2026

    tournament = _compiled(
        {"resource": "tournament", "filter": {"serie_id": 10828, "name": "Group Stage"}}
    )
    assert tournament.path == "/dota2/tournaments"
    assert tournament.params["filter[serie_id]"] == 10828
    assert tournament.params["filter[name]"] == "Group Stage"

    past_match = _compiled(
        {
            "resource": "match",
            "scope": "past",
            "filter": {"tournament_id": 21698},
            "search": {"name": "Grand Final"},
            "sort": ["-begin_at"],
        }
    )
    assert past_match.path == "/dota2/matches/past"
    assert past_match.params["sort"] == "-begin_at"
    assert _compiled({"resource": "match", "scope": "running"}).path == "/dota2/matches/running"


def test_compiler_uses_comma_separated_filter_range_and_sort_values() -> None:
    compiled = _compiled(
        {
            "resource": "match",
            "filter": {"league_id": [4106, 4107]},
            "range": {"begin_at": ["2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"]},
            "sort": ["-begin_at", "name"],
        }
    )

    assert compiled.params["filter[league_id]"] == "4106,4107"
    assert compiled.params["range[begin_at]"] == "2026-01-01T00:00:00Z,2026-02-01T00:00:00Z"
    assert compiled.params["sort"] == "-begin_at,name"


def test_executor_serializes_real_request_and_preserves_source_shape() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["query"] = request.url.query.decode()
        return httpx.Response(
            200,
            json=[
                {
                    "id": 21545,
                    "name": "Group Stage",
                    "serie_id": 10828,
                    "custom_unknown_field": {"x": 1},
                }
            ],
            request=request,
        )

    executor, adapter = _executor(handler)

    async def exercise():
        try:
            return await executor.execute(
                {"resource": "tournament", "filter": {"serie_id": 10828, "name": "Group Stage"}}
            )
        finally:
            await adapter.aclose()

    result = asyncio.run(exercise())
    assert seen["path"] == "/dota2/tournaments"
    assert seen["params"] == {
        "filter[serie_id]": "10828",
        "filter[name]": "Group Stage",
        "page[number]": "1",
        "page[size]": "10",
    }
    assert "filter%5Bname%5D=Group+Stage" in seen["query"]
    assert result.rows[0]["custom_unknown_field"] == {"x": 1}


def test_executor_rejects_invalid_query_before_http() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json=[], request=request)

    executor, adapter = _executor(handler)

    async def exercise() -> None:
        try:
            with pytest.raises(PandaScoreQueryValidationError) as error:
                await executor.execute({"resource": "tournament", "filter": {"league_id": 4106}})
            assert error.value.code == "unsupported_field"
        finally:
            await adapter.aclose()

    asyncio.run(exercise())
    assert request_count == 0


def test_executor_serializes_comma_separated_values_on_the_wire() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        seen["query"] = request.url.query.decode()
        return httpx.Response(200, json=[], request=request)

    executor, adapter = _executor(handler)

    async def exercise():
        try:
            return await executor.execute(
                {
                    "resource": "match",
                    "filter": {"league_id": [4106, 4107]},
                    "range": {"begin_at": ["2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"]},
                    "sort": ["-begin_at", "name"],
                }
            )
        finally:
            await adapter.aclose()

    asyncio.run(exercise())
    assert seen["params"]["filter[league_id]"] == "4106,4107"
    assert seen["params"]["range[begin_at]"] == "2026-01-01T00:00:00Z,2026-02-01T00:00:00Z"
    assert seen["params"]["sort"] == "-begin_at,name"
    assert "filter%5Bleague_id%5D=4106%2C4107" in seen["query"]


def test_executor_accepts_empty_collections_and_rejects_malformed_payloads() -> None:
    seen: dict[str, Any] = {}

    def empty_handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json=[], request=request)

    empty_executor, empty_adapter = _executor(empty_handler)

    async def fetch_empty():
        try:
            return await empty_executor.execute({"resource": "match", "scope": "running"})
        finally:
            await empty_adapter.aclose()

    assert asyncio.run(fetch_empty()).rows == []
    assert seen["path"] == "/dota2/matches/running"

    def malformed_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 123}, request=request)

    malformed_executor, malformed_adapter = _executor(malformed_handler)

    async def fetch_malformed() -> None:
        try:
            with pytest.raises(PandaScoreSchemaError, match="must be a list"):
                await malformed_executor.execute({"resource": "match", "scope": "running"})
        finally:
            await malformed_adapter.aclose()

    asyncio.run(fetch_malformed())
