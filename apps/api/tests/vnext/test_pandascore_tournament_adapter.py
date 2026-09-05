from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.vnext.capabilities.esports.tournament import TournamentSearchInput
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
