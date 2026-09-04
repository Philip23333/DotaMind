from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.vnext.capabilities.esports.match import MatchSearchInput
from app.vnext.providers.pandascore.client import (
    PandaScoreClient,
    PandaScoreConfigurationError,
    PandaScoreProtocolError,
)
from app.vnext.providers.pandascore.match_adapter import PandaScoreMatchAdapter


def _row() -> dict[str, Any]:
    return {
        "id": 42,
        "name": "Grand Final",
        "status": "finished",
        "scheduled_at": "2026-09-01T10:00:00Z",
        "begin_at": "2026-09-01T10:05:00Z",
        "end_at": "2026-09-01T12:00:00Z",
        "match_type": "best_of",
        "number_of_games": 3,
        "league": {"id": 1, "name": "The International"},
        "serie": {
            "id": 2,
            "name": "The International 2026",
            "full_name": "The International 2026",
            "year": 2026,
        },
        "tournament": {"id": 3, "name": "Group Stage"},
        "opponents": [
            {"opponent": {"id": 10, "name": "Alpha", "acronym": "ALP"}},
            {"opponent": {"id": 11, "name": "Beta", "acronym": "BET"}},
        ],
        "results": [{"team_id": 10, "score": 2}, {"team_id": 11, "score": 1}],
        "winner_id": 10,
    }


def _adapter(handler) -> PandaScoreMatchAdapter:
    client = PandaScoreClient(
        base_url="https://api.pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    return PandaScoreMatchAdapter(client)


@pytest.mark.parametrize(
    ("lifecycle", "path"),
    [
        (None, "/dota2/matches"),
        ("past", "/dota2/matches/past"),
        ("running", "/dota2/matches/running"),
        ("upcoming", "/dota2/matches/upcoming"),
    ],
)
def test_search_uses_one_lifecycle_collection_request(lifecycle: str | None, path: str) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[_row()], request=request)

    query = MatchSearchInput(
        lifecycle=lifecycle,
        id=42,
        league_id=1,
        series_id=2,
        tournament_id=3,
        team_id=10,
        name="Final",
        sort="begin_at_desc",
        page=2,
        limit=7,
    )
    result = asyncio.run(_adapter(handler).search(query))

    assert len(calls) == 1
    assert calls[0] == (
        path,
        {
            "page": "2",
            "per_page": "7",
            "filter[id]": "42",
            "filter[league_id]": "1",
            "filter[serie_id]": "2",
            "filter[tournament_id]": "3",
            "filter[opponent_id]": "10",
            "search[name]": "Final",
            "sort": "-begin_at",
        },
    )
    assert result.page == 2
    assert result.limit == 7


def test_adapter_normalizes_source_wrappers_into_semantic_match_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_row()], request=request)

    item = asyncio.run(
        _adapter(handler).search(MatchSearchInput())
    ).items[0]

    assert item.id == 42
    assert item.series is not None
    assert item.series.id == 2
    assert item.series.year == 2026
    assert [team.id for team in item.opponents] == [10, 11]
    assert [(score.team_id, score.score) for score in item.results] == [(10, 2), (11, 1)]
    assert item.winner_id == 10
    assert not hasattr(item, "serie")


def test_client_rejects_missing_token_and_non_collection_payload() -> None:
    missing = PandaScoreClient(base_url="https://api.pandascore.test", token="")
    with pytest.raises(PandaScoreConfigurationError):
        asyncio.run(missing.get_list("/dota2/matches", params={}))

    def object_payload(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": []}, request=request)

    invalid = PandaScoreClient(
        base_url="https://api.pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(object_payload),
    )
    with pytest.raises(PandaScoreProtocolError):
        asyncio.run(invalid.get_list("/dota2/matches", params={}))
