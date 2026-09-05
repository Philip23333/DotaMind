from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.vnext.capabilities.esports.tournament import (
    TournamentRostersInput,
    TournamentSearchInput,
)
from app.vnext.providers.pandascore.client import PandaScoreClient
from app.vnext.providers.pandascore.tournament_adapter import PandaScoreTournamentAdapter


def _adapter(handler) -> PandaScoreTournamentAdapter:
    client = PandaScoreClient(
        base_url="https://api.pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    return PandaScoreTournamentAdapter(client)


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": 21545,
        "name": "Group Stage",
        "serie_id": 10828,
        "begin_at": "2026-08-13T02:00:00Z",
        "end_at": "2026-08-15T15:47:47Z",
        "slug": "the-international-2026-group-stage",
        "tier": "s",
        "prizepool": "1000000",
    }
    row.update(overrides)
    return row


def _roster_row(
    team_id: int = 128329,
    team_name: str = "Xtreme Gaming",
    acronym: str = "XG",
    players: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "team": {"id": team_id, "name": team_name, "acronym": acronym},
        "players": players
        if players is not None
        else [
            {
                "id": 123 + index,
                "name": name,
                "first_name": None if index == 0 else f"First{index}",
                "last_name": None if index == 0 else f"Last{index}",
                "role": None if index == 0 else "player",
                "current_team": {"id": team_id, "name": team_name},
            }
            for index, name in enumerate(("Ame", "Xm", "NothingToSay", "Pyw", "XinQ"))
        ],
    }


def test_tournament_mapping_uses_one_collection_request() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[_row()], request=request)

    query = TournamentSearchInput(
        id=21545,
        series_id=10828,
        name="Group Stage",
        page=2,
        limit=50,
    )
    result = asyncio.run(_adapter(handler).search(query))

    assert calls == [
        (
            "/dota2/tournaments",
            {
                "page": "2",
                "per_page": "50",
                "filter[id]": "21545",
                "filter[serie_id]": "10828",
                "search[name]": "Group Stage",
            },
        )
    ]
    assert result.page == 2
    assert result.limit == 50


@pytest.mark.parametrize(
    "row",
    [_row(), _row(serie_id=None, serie={"id": 10828, "name": "2026"})],
)
def test_tournament_normalization_translates_series_identity(row: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[row], request=request)

    item = asyncio.run(_adapter(handler).search(TournamentSearchInput())).items[0]

    assert item.model_dump(mode="json") == {
        "id": 21545,
        "name": "Group Stage",
        "series_id": 10828,
        "begin_at": "2026-08-13T02:00:00Z",
        "end_at": "2026-08-15T15:47:47Z",
    }
    assert not hasattr(item, "serie_id")
    assert not hasattr(item, "slug")
    assert not hasattr(item, "tier")
    assert not hasattr(item, "prizepool")


def test_tournament_rosters_uses_tournament_roster_endpoint() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[_roster_row()], request=request)

    result = asyncio.run(
        _adapter(handler).rosters(TournamentRostersInput(tournament_id=14384))
    )

    assert calls == [("/tournaments/14384/rosters", {})]
    roster = result.items[0]
    assert roster.team.model_dump() == {
        "id": 128329,
        "name": "Xtreme Gaming",
        "acronym": "XG",
    }
    assert len(roster.players) == 5
    assert roster.players[0].model_dump() == {
        "id": 123,
        "name": "Ame",
        "first_name": None,
        "last_name": None,
        "role": None,
    }
    assert not hasattr(roster.players[0], "current_team")


def test_tournament_rosters_filters_team_locally() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                _roster_row(),
                _roster_row(team_id=999, team_name="Example Team", acronym="EX"),
            ],
            request=request,
        )

    result = asyncio.run(
        _adapter(handler).rosters(
            TournamentRostersInput(tournament_id=14384, team_id=999)
        )
    )

    assert len(result.items) == 1
    assert result.items[0].team.id == 999


def test_tournament_rosters_missing_team_returns_empty_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_roster_row()], request=request)

    result = asyncio.run(
        _adapter(handler).rosters(
            TournamentRostersInput(tournament_id=14384, team_id=404)
        )
    )

    assert result.items == []
