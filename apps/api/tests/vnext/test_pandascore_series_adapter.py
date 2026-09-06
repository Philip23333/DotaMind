from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.vnext.capabilities.esports.series import SeriesSearchInput, SeriesTeamsInput
from app.vnext.providers.pandascore.client import PandaScoreClient
from app.vnext.providers.pandascore.series_adapter import PandaScoreSeriesAdapter


def _adapter(handler) -> PandaScoreSeriesAdapter:
    client = PandaScoreClient(
        base_url="https://api.pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    return PandaScoreSeriesAdapter(client)


def _row() -> dict[str, Any]:
    return {
        "id": 10828,
        "name": "",
        "full_name": "2026",
        "season": "2026",
        "year": 2026,
        "begin_at": "2026-08-01T00:00:00Z",
        "end_at": "2026-09-01T00:00:00Z",
        "league": {"id": 4106, "name": "The International"},
        "slug": "the-international-2026",
        "modified_at": "2026-09-01T00:00:00Z",
    }


def _team_row() -> dict[str, Any]:
    return {
        "id": 128329,
        "name": "Xtreme Gaming",
        "acronym": "XG",
        "location": "cn",
        "players": [{"id": 123, "name": "Ame"}],
    }


def test_series_mapping_compiles_all_criteria_into_one_request() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[_row()], request=request)

    query = SeriesSearchInput(
        id=10828,
        league_id=4106,
        tournament_id=21545,
        team_id=123,
        year=2026,
        name="The International",
        season="2026",
        winner_id=123,
        tier="s",
        page=2,
        limit=50,
    )
    result = asyncio.run(_adapter(handler).search(query))

    assert calls == [
        (
            "/dota2/series",
            {
                "page": "2",
                "per_page": "50",
                "filter[id]": "10828",
                "filter[league_id]": "4106",
                "filter[tournament_id]": "21545",
                "filter[opponent_id]": "123",
                "filter[year]": "2026",
                "filter[winner_id]": "123",
                "filter[tier]": "s",
                "search[name]": "The International",
                "search[season]": "2026",
            },
        )
    ]
    assert result.page == 2
    assert result.limit == 50


def test_series_team_and_league_filters_are_compiled_together() -> None:
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        return httpx.Response(200, json=[], request=request)

    asyncio.run(_adapter(handler).search(SeriesSearchInput(team_id=123, league_id=456)))

    assert calls == [
        {
            "page": "1",
            "per_page": "20",
            "filter[league_id]": "456",
            "filter[opponent_id]": "123",
        }
    ]


def test_series_ti_discovery_filters_parent_and_year() -> None:
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        return httpx.Response(200, json=[], request=request)

    asyncio.run(_adapter(handler).search(SeriesSearchInput(league_id=4106, year=2026)))

    assert calls == [
        {
            "page": "1",
            "per_page": "20",
            "filter[league_id]": "4106",
            "filter[year]": "2026",
        }
    ]


def test_series_normalization_preserves_edition_identity_without_provider_clutter() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_row()], request=request)

    item = asyncio.run(_adapter(handler).search(SeriesSearchInput())).items[0]

    assert item.model_dump(mode="json") == {
        "id": 10828,
        "name": "",
        "full_name": "2026",
        "season": "2026",
        "year": 2026,
        "begin_at": "2026-08-01T00:00:00Z",
        "end_at": "2026-09-01T00:00:00Z",
        "league": {"id": 4106, "name": "The International"},
    }
    assert not hasattr(item, "slug")
    assert not hasattr(item, "modified_at")


def test_series_teams_uses_supported_series_participants_endpoint() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[_team_row()], request=request)

    result = asyncio.run(
        _adapter(handler).teams(SeriesTeamsInput(series_id=10828, page=2, limit=50))
    )

    assert calls == [
        (
            "/dota2/series/10828/teams",
            {"page": "2", "per_page": "50"},
        )
    ]
    assert result.model_dump(mode="json") == {
        "items": [
            {
                "id": 128329,
                "name": "Xtreme Gaming",
                "acronym": "XG",
                "location": "cn",
            }
        ],
        "page": 2,
        "limit": 50,
    }
