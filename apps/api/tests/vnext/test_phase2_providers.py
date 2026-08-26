from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.vnext.providers.opendota.adapter import (
    OpenDotaAdapter,
    OpenDotaHTTPError,
    OpenDotaSchemaError,
)
from app.vnext.providers.opendota.models import OpenDotaGameConstructionMatch
from app.vnext.providers.pandascore.adapter import (
    PandaScoreAdapter,
    PandaScoreHTTPError,
    PandaScoreSchemaError,
)
from tests.vnext.phase2_support import load_fixture


def _json_response(request: httpx.Request, payload: Any) -> httpx.Response:
    return httpx.Response(200, json=payload, request=request)


def test_pandascore_adapter_uses_bearer_pagination_and_dota_paths() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/dota2/series":
            return _json_response(request, load_fixture("pandascore", "series_search.json"))
        if request.url.path == "/dota2/matches/past":
            return _json_response(request, load_fixture("pandascore", "matches_past.json"))
        if request.url.path == "/dota2/matches/30001":
            return _json_response(request, load_fixture("pandascore", "match_30001.json"))
        raise AssertionError(request.url)

    async def exercise() -> tuple[Any, Any, Any]:
        adapter = PandaScoreAdapter(
            base_url="https://pandascore.test",
            token="test-token",
            transport=httpx.MockTransport(handler),
        )
        series = await adapter.search_series(query="The International", year=2026, limit=7)
        matches = await adapter.list_matches(scope="recent", series_id=20001, limit=7)
        match = await adapter.get_match(30001)
        await adapter.aclose()
        return series, matches, match

    series, matches, match = asyncio.run(exercise())
    assert len(series.items) == 4
    assert len(matches.items) == 2
    assert match.item.provider_id == 30001
    assert seen[0].headers["authorization"] == "Bearer test-token"
    assert seen[0].url.params["page[size]"] == "7"
    assert seen[0].url.params["page[number]"] == "1"
    assert seen[0].url.params["filter[year]"] == "2026"
    assert seen[1].url.params["filter[serie_id]"] == "20001"


def test_pandascore_adapter_translates_http_and_schema_failures() -> None:
    def http_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="secret response body", request=request)

    def bad_schema(request: httpx.Request) -> httpx.Response:
        return _json_response(request, [{"name": "missing id"}])

    async def call(adapter: PandaScoreAdapter) -> None:
        await adapter.search_series()

    with pytest.raises(PandaScoreHTTPError) as error:
        asyncio.run(
            call(
                PandaScoreAdapter(
                    base_url="https://pandascore.test",
                    token="test-token",
                    transport=httpx.MockTransport(http_error),
                )
            )
        )
    assert error.value.status_code == 403
    assert "secret response body" not in str(error.value)

    with pytest.raises(PandaScoreSchemaError):
        asyncio.run(
            call(
                PandaScoreAdapter(
                    base_url="https://pandascore.test",
                    token="test-token",
                    transport=httpx.MockTransport(bad_schema),
                )
            )
        )


def test_opendota_adapter_parses_league_team_match_and_detail_with_key_query() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/leagues"):
            return _json_response(request, load_fixture("opendota", "leagues.json"))
        if request.url.path.endswith("/teams"):
            return _json_response(request, load_fixture("opendota", "teams.json"))
        if request.url.path.endswith("/leagues/9001/matches"):
            return _json_response(request, load_fixture("opendota", "league_matches_9001.json"))
        if request.url.path.endswith("/matches/40001"):
            return _json_response(request, load_fixture("opendota", "match_detail_40001.json"))
        raise AssertionError(request.url)

    async def exercise() -> tuple[Any, Any, Any, Any]:
        adapter = OpenDotaAdapter(
            base_url="https://opendota.test/api",
            api_key="test-api-key",
            transport=httpx.MockTransport(handler),
        )
        leagues = await adapter.list_leagues()
        teams = await adapter.list_teams()
        matches = await adapter.list_league_matches(9001)
        detail = await adapter.get_match_detail(40001)
        await adapter.aclose()
        return leagues, teams, matches, detail

    leagues, teams, matches, detail = asyncio.run(exercise())
    assert leagues.items[0].provider_id == 9001
    assert teams.items[0].provider_id == 9101
    assert matches.items[0].provider_match_id == 40001
    assert detail.item.provider_match_id == 40001
    assert all(request.url.params["api_key"] == "test-api-key" for request in seen)


def test_opendota_adapter_sanitizes_http_and_invalid_payloads() -> None:
    def http_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="private upstream details", request=request)

    def bad_schema(request: httpx.Request) -> httpx.Response:
        return _json_response(request, [{"name": "missing league id"}])

    async def call(adapter: OpenDotaAdapter) -> None:
        await adapter.list_leagues()

    with pytest.raises(OpenDotaHTTPError) as error:
        asyncio.run(
            call(
                OpenDotaAdapter(
                    base_url="https://opendota.test/api",
                    transport=httpx.MockTransport(http_error),
                )
            )
        )
    assert error.value.status_code == 500
    assert "private upstream details" not in str(error.value)

    with pytest.raises(OpenDotaSchemaError):
        asyncio.run(
            call(
                OpenDotaAdapter(
                    base_url="https://opendota.test/api",
                    transport=httpx.MockTransport(bad_schema),
                )
            )
        )


def test_opendota_typed_construction_fetch_validates_and_preserves_identity() -> None:
    requested_match_id = 8123456789
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json_response(request, {"match_id": requested_match_id})

    async def exercise():
        adapter = OpenDotaAdapter(
            base_url="https://opendota.test/api",
            transport=httpx.MockTransport(handler),
        )
        result = await adapter.get_game_construction_match(requested_match_id)
        await adapter.aclose()
        return result

    result = asyncio.run(exercise())

    assert isinstance(result.item, OpenDotaGameConstructionMatch)
    assert result.item.match_id == requested_match_id
    assert result.fetched_at is not None
    assert seen[0].url.path == f"/api/matches/{requested_match_id}"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"match_id": 4567},
    ],
)
def test_opendota_typed_construction_fetch_rejects_missing_or_mismatched_identity(
    payload: dict[str, Any],
) -> None:
    requested_match_id = 8123

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(request, payload)

    async def call() -> None:
        adapter = OpenDotaAdapter(
            base_url="https://opendota.test/api",
            transport=httpx.MockTransport(handler),
        )
        await adapter.get_game_construction_match(requested_match_id)

    with pytest.raises(OpenDotaSchemaError):
        asyncio.run(call())
