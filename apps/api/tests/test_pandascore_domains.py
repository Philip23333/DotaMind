from __future__ import annotations

from datetime import date

import pytest

from app.integrations.pandascore.competitions import PandaScoreCompetitions, normalize_competition
from app.integrations.pandascore.matches import PandaScoreMatches, normalize_match

SAMPLE_MATCH = {
    "id": 1631694,
    "name": "Round 2: NGX vs OG",
    "status": "finished",
    "scheduled_at": "2026-08-13T09:30:00Z",
    "begin_at": "2026-08-13T09:34:25Z",
    "end_at": "2026-08-13T12:25:00Z",
    "serie_id": 10828,
    "tournament_id": 21545,
    "number_of_games": 3,
    "opponents": [
        {"type": "Team", "opponent": {"id": 129609, "name": "Nigma Galaxy", "acronym": "NGX"}},
        {"type": "Team", "opponent": {"id": 1654, "name": "OG", "acronym": "OG"}},
    ],
    "results": [{"score": 2, "team_id": 129609}, {"score": 0, "team_id": 1654}],
    "streams_list": [],
    "tournament": {"id": 21545, "name": "Group Stage", "serie_id": 10828},
    "games": [
        {"id": 738652, "position": 1, "status": "finished", "length": 3227, "match_id": 1631694},
        {"id": 738653, "position": 2, "status": "finished", "length": 4461, "match_id": 1631694},
    ],
}


class FakeTransport:
    max_page_size = 100

    def __init__(self, rows: dict[str, list[dict]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict]] = []

    async def get(self, path: str, *, params=None, cache_ttl_seconds=None):
        endpoint = path.rsplit("/", 1)[-1]
        self.calls.append((path, params or {}))
        return self.rows.get(endpoint, [])


@pytest.mark.anyio
async def test_fixture_listing_merges_and_deduplicates_endpoints() -> None:
    transport = FakeTransport(
        {
            "past": [SAMPLE_MATCH],
            "upcoming": [SAMPLE_MATCH],
            "running": [],
        }
    )
    client = PandaScoreMatches(transport, object())
    rows = await client.list_matches(10828)
    assert len(rows) == 1
    assert rows[0].pandascore_match_id == 1631694
    assert rows[0].games[0].pandascore_game_id == 738652
    assert rows[0].games[0].pandascore_match_id == 1631694
    assert rows[0].games[0].valve_match_id is None
    assert all(params["sort"] == "-scheduled_at" for _path, params in transport.calls)
    assert all(params["page[size]"] == 100 for _path, params in transport.calls)


@pytest.mark.anyio
async def test_fixture_listing_returns_newest_first_and_pushes_requested_limit() -> None:
    oldest = {**SAMPLE_MATCH, "id": 1, "scheduled_at": "2026-08-13T09:30:00Z"}
    newest = {**SAMPLE_MATCH, "id": 2, "scheduled_at": "2026-08-20T13:25:00Z"}
    transport = FakeTransport({"past": [oldest], "upcoming": [newest], "running": []})

    rows = await PandaScoreMatches(transport, object()).list_matches(10828, limit=20)

    assert [row.pandascore_match_id for row in rows] == [2, 1]
    assert all(params["sort"] == "-scheduled_at" for _path, params in transport.calls)
    assert all(params["page[size]"] == 20 for _path, params in transport.calls)


@pytest.mark.anyio
async def test_team_order_independent_resolution_returns_selected_game() -> None:
    transport = FakeTransport({"past": [SAMPLE_MATCH], "upcoming": [], "running": []})
    client = PandaScoreMatches(transport, object())
    result = await client.resolve_games(
        10828, ["OG", "Nigma"], game_number=1, scheduled_date=date(2026, 8, 13)
    )
    assert result.status == "resolved"
    assert result.match is not None
    assert [game.pandascore_game_id for game in result.games] == [738652]
    assert result.games[0].valve_match_id is None


@pytest.mark.anyio
async def test_missing_game_number_returns_all_games_in_series() -> None:
    transport = FakeTransport({"past": [SAMPLE_MATCH], "upcoming": [], "running": []})
    result = await PandaScoreMatches(transport, object()).resolve_games(10828, ["NGX", "OG"])
    assert result.status == "resolved"
    assert [game.position for game in result.games] == [1, 2]


def test_competition_normalization_keeps_provider_ids_explicit() -> None:
    row = normalize_competition(
        {
            "id": 10828,
            "name": "",
            "full_name": "2026",
            "year": 2026,
            "league": {"id": 4106, "name": "The International"},
            "tournaments": [],
        }
    )
    assert row.pandascore_series_id == 10828
    assert row.name == "The International"


def test_match_normalization_does_not_mislabel_games_match_id() -> None:
    row = normalize_match(SAMPLE_MATCH)
    assert row.games[0].pandascore_match_id == 1631694
    assert row.games[0].valve_match_id is None


@pytest.mark.anyio
async def test_series_listing_pushes_year_filter_only_when_requested() -> None:
    transport = FakeTransport({"series": []})
    client = PandaScoreCompetitions(transport)

    await client.list_series(year=2025)
    assert transport.calls[-1][1]["filter[year]"] == 2025

    await client.list_series()
    assert "filter[year]" not in transport.calls[-1][1]
