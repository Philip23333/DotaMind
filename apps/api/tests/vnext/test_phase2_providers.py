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
from app.vnext.providers.pandascore.models import PandaScoreTeam
from tests.vnext.phase2_support import load_fixture


def _json_response(
    request: httpx.Request,
    payload: Any,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(200, json=payload, headers=headers, request=request)


def _panda_match(provider_id: int) -> dict[str, Any]:
    return {
        "id": provider_id,
        "name": f"Match {provider_id}",
        "status": "finished",
    }


def test_pandascore_adapter_uses_bearer_pagination_and_dota_paths() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/dota2/series":
            return _json_response(
                request,
                load_fixture("pandascore", "series_search.json"),
                headers={"X-Total": "4"},
            )
        if request.url.path == "/dota2/matches/past":
            return _json_response(
                request,
                load_fixture("pandascore", "matches_past.json"),
                headers={
                    "Link": (
                        '<https://pandascore.test/dota2/matches/past?page[number]=2>; '
                        'rel="next"'
                    )
                },
            )
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
    assert series.has_more is False
    assert matches.has_more is True
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
    assert "test-token" not in str(error.value)

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


def test_pandascore_adapter_discovers_leagues_and_league_series() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/dota2/leagues":
            return _json_response(request, [{"id": 123, "name": "The International"}])
        if request.url.path == "/leagues/123/series":
            return _json_response(request, load_fixture("pandascore", "series_search.json"))
        raise AssertionError(request.url)

    async def exercise():
        adapter = PandaScoreAdapter(
            base_url="https://pandascore.test",
            token="test-token",
            transport=httpx.MockTransport(handler),
        )
        leagues = await adapter.search_leagues(query="The International", limit=7)
        series = await adapter.list_league_series(123, year=2026, limit=7)
        await adapter.aclose()
        return leagues, series

    leagues, series = asyncio.run(exercise())

    assert leagues.items[0].provider_id == 123
    assert leagues.items[0].name == "The International"
    assert len(series.items) == 4
    assert series.items[0].provider_id == 20001
    assert seen[0].url.path == "/dota2/leagues"
    assert seen[0].url.params["search[name]"] == "The International"
    assert seen[0].url.params["page[size]"] == "7"
    assert seen[0].url.params["page[number]"] == "1"
    assert seen[1].url.path == "/leagues/123/series"
    assert seen[1].url.params["filter[year]"] == "2026"
    assert seen[1].url.params["page[size]"] == "7"


def test_pandascore_adapter_discovers_teams_and_queries_team_matches() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/dota2/teams":
            return _json_response(
                request,
                [
                    {
                        "id": 501,
                        "name": "Team Alpha",
                        "acronym": "TA",
                        "slug": "team-alpha",
                        "image_url": "https://cdn.pandascore.test/team-alpha.png",
                    }
                ],
                headers={
                    "Link": '<https://pandascore.test/dota2/teams?page[number]=2>; rel="next"'
                },
            )
        if request.url.path == "/teams/501/matches":
            return _json_response(
                request,
                [{**_panda_match(70001), "serie_id": 999}],
                headers={"X-Total": "5"},
            )
        raise AssertionError(request.url)

    async def exercise() -> tuple[Any, Any]:
        adapter = PandaScoreAdapter(
            base_url="https://pandascore.test",
            token="test-token",
            transport=httpx.MockTransport(handler),
        )
        teams = await adapter.search_teams(query="Team Alpha", limit=7)
        matches = await adapter.list_team_matches(
            501,
            page_number=2,
            page_size=2,
            sort="-scheduled_at",
            query="Match",
            series_id=20001,
        )
        await adapter.aclose()
        return teams, matches

    teams, matches = asyncio.run(exercise())

    assert isinstance(teams.items[0], PandaScoreTeam)
    assert teams.items[0].provider_id == 501
    assert teams.items[0].name == "Team Alpha"
    assert teams.has_more is True
    assert matches.items[0].provider_id == 70001
    assert matches.items[0].series_id == 999
    assert matches.has_more is True

    assert seen[0].headers["authorization"] == "Bearer test-token"
    assert seen[0].url.path == "/dota2/teams"
    assert seen[0].url.params["search[name]"] == "Team Alpha"
    assert seen[0].url.params["page[number]"] == "1"
    assert seen[0].url.params["page[size]"] == "7"

    assert seen[1].headers["authorization"] == "Bearer test-token"
    assert seen[1].url.path == "/teams/501/matches"
    assert seen[1].url.params["page[number]"] == "2"
    assert seen[1].url.params["page[size]"] == "2"
    assert seen[1].url.params["sort"] == "-scheduled_at"
    assert seen[1].url.params["search[name]"] == "Match"
    assert seen[1].url.params["filter[serie_id]"] == "20001"
    assert all("test-token" not in str(request.url) for request in seen)


def test_pandascore_adapter_all_scope_marks_truncation_after_merge() -> None:
    payloads = {
        "/dota2/matches/upcoming": [_panda_match(80001), _panda_match(80002)],
        "/dota2/matches/running": [_panda_match(80002), _panda_match(80003)],
        "/dota2/matches/past": [_panda_match(80003), _panda_match(80004)],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(request, payloads[request.url.path])

    async def exercise() -> Any:
        adapter = PandaScoreAdapter(
            base_url="https://pandascore.test",
            token="test-token",
            transport=httpx.MockTransport(handler),
        )
        result = await adapter.list_matches(scope="all", limit=3)
        await adapter.aclose()
        return result

    result = asyncio.run(exercise())

    assert [item.provider_id for item in result.items] == [80001, 80002, 80003]
    assert result.has_more is True


@pytest.mark.parametrize(
    ("headers", "payload", "expected_has_more"),
    [
        ({"X-Total": "5"}, [_panda_match(701), _panda_match(702)], True),
        (
            {"Link": '<https://pandascore.test/teams/501/matches?page[number]=3>; rel="next"'},
            [_panda_match(703), _panda_match(704)],
            True,
        ),
        (
            {"Link": '<https://pandascore.test/teams/501/matches?page[number]=2>; rel="last"'},
            [_panda_match(705), _panda_match(706)],
            False,
        ),
        ({}, [_panda_match(707), _panda_match(708)], True),
        ({}, [_panda_match(709)], False),
    ],
)
def test_pandascore_adapter_propagates_header_and_conservative_pagination(
    headers: dict[str, str],
    payload: list[dict[str, Any]],
    expected_has_more: bool,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(request, payload, headers=headers)

    async def exercise() -> Any:
        adapter = PandaScoreAdapter(
            base_url="https://pandascore.test",
            token="test-token",
            transport=httpx.MockTransport(handler),
        )
        result = await adapter.list_team_matches(501, page_number=2, page_size=2)
        await adapter.aclose()
        return result

    result = asyncio.run(exercise())

    assert result.has_more is expected_has_more


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
