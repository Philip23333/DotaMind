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
        "slug": " grand-final ",
        "status": "finished",
        "match_type": " best_of ",
        "number_of_games": 3,
        "scheduled_at": "2026-09-01T10:00:00Z",
        "original_scheduled_at": "2026-09-01T09:30:00Z",
        "begin_at": "2026-09-01T10:05:00Z",
        "end_at": "2026-09-01T12:00:00Z",
        "league_id": 1,
        "serie_id": 2,
        "tournament_id": 3,
        "league": {"id": 1, "name": "The International"},
        "serie": {
            "id": 2,
            "name": "The International 2026",
            "full_name": "The International 2026",
            "year": 2026,
        },
        "tournament": {"id": 3, "name": "Group Stage"},
        "opponents": [
            {
                "opponent": {
                    "id": 10,
                    "name": "Alpha",
                    "acronym": " ALP ",
                    "location": " us ",
                    "slug": " alpha ",
                    "image_url": " https://example.test/alpha.png ",
                    "players": [{"id": 100, "name": "Current"}],
                    "modified_at": "2026-09-01T00:00:00Z",
                }
            },
            {
                "opponent": {
                    "id": 11,
                    "name": "Beta",
                    "acronym": " BET ",
                    "location": " ca ",
                    "slug": " beta ",
                    "image_url": " https://example.test/beta.png ",
                    "players": [],
                    "modified_at": "2026-09-01T00:00:00Z",
                }
            },
        ],
        "results": [{"team_id": 10, "score": 2}, {"team_id": 11, "score": 1}],
        "winner_id": 10,
        "winner": {
            "id": 10,
            "name": "Alpha",
            "acronym": " ALP ",
            "location": " us ",
            "slug": " alpha ",
            "image_url": " https://example.test/alpha.png ",
        },
        "games": [
            {
                "id": 9001,
                "position": 1,
                "status": "finished",
                "begin_at": "2026-09-01T10:05:00Z",
                "end_at": "2026-09-01T10:45:00Z",
                "length": 2400,
                "winner": {"id": 10, "type": "Team"},
                "complete": True,
                "forfeit": False,
                "match_id": 42,
                "finished": True,
                "detailed_stats": True,
            }
        ],
        "draw": False,
        "forfeit": False,
        "rescheduled": False,
        "winner_type": "Team",
        "modified_at": "2026-09-01T00:00:00Z",
        "videogame": {"id": 4},
        "videogame_title": None,
        "videogame_version": "7.39",
        "streams_list": [],
        "live": {"opens_at": None},
        "detailed_stats": True,
        "game_advantage": None,
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
        winner_id=11,
        name="Final",
        sort="begin_at_desc",
        page=2,
        limit=7,
    )
    result = asyncio.run(_adapter(handler).search(query))

    assert len(calls) == 1
    expected_params = {
        "page": "2",
        "per_page": "7",
        "filter[id]": "42",
        "filter[league_id]": "1",
        "filter[serie_id]": "2",
        "filter[tournament_id]": "3",
        "filter[opponent_id]": "10",
        "filter[winner_id]": "11",
        "search[name]": "Final",
        "sort": "-begin_at",
    }
    assert calls[0] == (path, expected_params)
    assert result.page == 2
    assert result.limit == 7
    assert result.anomalies == []


def test_match_search_skips_malformed_top_level_items() -> None:
    first = _row()
    second = _row()
    second["id"] = 43

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[first, "bad-row", second], request=request)

    result = asyncio.run(_adapter(handler).search(MatchSearchInput()))

    assert [item.id for item in result.items] == [42, 43]
    assert len(result.anomalies) == 1
    assert result.anomalies[0].path == "provider.items[1]"
    assert result.anomalies[0].reason == "provider item is not an object"
    assert result.anomalies[0].provider_id is None


def test_match_games_have_partial_success() -> None:
    row = _row()
    template = row["games"][0]
    row["games"] = [
        {**template, "id": 9001},
        {**template, "id": 9002, "position": 2},
        {"id": 9003},
        {**template, "id": 9004, "position": 4},
        {**template, "id": 9005, "position": 5},
    ]

    anomalies = []
    item = PandaScoreMatchAdapter._normalize(
        row,
        path="provider.items[0]",
        anomalies=anomalies,
    )

    assert len(item.games) == 4
    assert len(anomalies) == 1
    assert "games" in anomalies[0].path
    assert anomalies[0].reason
    assert anomalies[0].provider_id == 9003


def test_adapter_normalizes_complete_match_projection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_row()], request=request)

    item = asyncio.run(
        _adapter(handler).search(MatchSearchInput())
    ).items[0]

    assert item.model_dump(mode="json") == {
        "id": 42,
        "name": "Grand Final",
        "slug": "grand-final",
        "status": "finished",
        "match_type": "best_of",
        "number_of_games": 3,
        "begin_at": "2026-09-01T10:05:00Z",
        "end_at": "2026-09-01T12:00:00Z",
        "scheduled_at": "2026-09-01T10:00:00Z",
        "original_scheduled_at": "2026-09-01T09:30:00Z",
        "league_id": 1,
        "series_id": 2,
        "tournament_id": 3,
        "participants": [
            {
                "team": {
                    "id": 10,
                    "name": "Alpha",
                    "acronym": "ALP",
                    "location": "us",
                    "slug": "alpha",
                    "image_url": "https://example.test/alpha.png",
                },
                "score": 2,
            },
            {
                "team": {
                    "id": 11,
                    "name": "Beta",
                    "acronym": "BET",
                    "location": "ca",
                    "slug": "beta",
                    "image_url": "https://example.test/beta.png",
                },
                "score": 1,
            },
        ],
        "winner_id": 10,
        "winner": {
            "id": 10,
            "name": "Alpha",
            "acronym": "ALP",
            "location": "us",
            "slug": "alpha",
            "image_url": "https://example.test/alpha.png",
        },
        "games": [
            {
                "id": 9001,
                "position": 1,
                "status": "finished",
                "begin_at": "2026-09-01T10:05:00Z",
                "end_at": "2026-09-01T10:45:00Z",
                "length": 2400,
                "winner_id": 10,
                "complete": True,
                "forfeit": False,
            }
        ],
        "draw": False,
        "forfeit": False,
        "rescheduled": False,
    }
    for field in (
        "league",
        "serie",
        "series",
        "tournament",
        "opponents",
        "results",
        "winner_type",
        "modified_at",
        "videogame",
        "streams_list",
        "live",
    ):
        assert not hasattr(item, field)


def test_match_participants_preserve_missing_and_zero_scores() -> None:
    missing_score_row = _row()
    missing_score_row["results"] = [{"team_id": 10, "score": 2}]
    missing_score_item = PandaScoreMatchAdapter._normalize(missing_score_row)
    assert [participant.score for participant in missing_score_item.participants] == [2, None]

    zero_score_row = _row()
    zero_score_row["status"] = "canceled"
    zero_score_row["results"] = [{"team_id": 10, "score": 0}, {"team_id": 11, "score": 0}]
    zero_score_item = PandaScoreMatchAdapter._normalize(zero_score_row)
    assert [participant.score for participant in zero_score_item.participants] == [0, 0]


def test_orphan_match_result_is_ignored_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    row = _row()
    row["results"] = [
        {"team_id": 10, "score": 2},
        {"team_id": 11, "score": 1},
        {"team_id": 123, "score": 9},
    ]

    with caplog.at_level("WARNING"):
        anomalies = []
        item = PandaScoreMatchAdapter._normalize(row, anomalies=anomalies)

    assert [participant.team.id for participant in item.participants] == [10, 11]
    assert "team_id=123" in caplog.text
    assert "match id=42" in caplog.text
    assert anomalies[0].path == "provider.items[0].results[2]"
    assert anomalies[0].reason == "result references unknown opponent"
    assert anomalies[0].provider_id == 123


def test_winner_id_is_preserved_when_winner_object_is_missing() -> None:
    row = _row()
    row["winner"] = None

    item = PandaScoreMatchAdapter._normalize(row)

    assert item.winner_id == 10
    assert item.winner is None


def test_parent_ids_do_not_fallback_to_nested_objects() -> None:
    row = _row()
    row.pop("league_id")
    row.pop("serie_id")
    row.pop("tournament_id")

    item = PandaScoreMatchAdapter._normalize(row)

    assert item.league_id is None
    assert item.series_id is None
    assert item.tournament_id is None


def test_required_match_and_game_booleans_are_not_defaulted() -> None:
    missing_match_boolean = _row()
    missing_match_boolean.pop("draw")
    with pytest.raises(KeyError, match="draw"):
        PandaScoreMatchAdapter._normalize(missing_match_boolean)

    missing_game_boolean = _row()
    missing_game_boolean["games"][0].pop("complete")
    anomalies = []
    item = PandaScoreMatchAdapter._normalize(
        missing_game_boolean,
        path="provider.items[0]",
        anomalies=anomalies,
    )
    assert item.games == []
    assert anomalies[0].path == "provider.items[0].games[0]"
    assert "complete" in anomalies[0].reason


def test_past_does_not_implicitly_filter_finished_and_explicit_status_is_preserved() -> None:
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        return httpx.Response(200, json=[], request=request)

    adapter = _adapter(handler)
    asyncio.run(adapter.search(MatchSearchInput(team_id=123, lifecycle="past")))
    asyncio.run(
        adapter.search(
            MatchSearchInput(team_id=123, lifecycle="past", status="finished")
        )
    )

    assert calls[0]["filter[opponent_id]"] == "123"
    assert "filter[status]" not in calls[0]
    assert calls[1]["filter[opponent_id]"] == "123"
    assert calls[1]["filter[status]"] == "finished"


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
