from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.vnext.providers.pandascore.client import PandaScoreClient
from app.vnext.providers.pandascore.team_directory import (
    PandaScoreTeamDirectoryError,
    PandaScoreTeamDirectoryReader,
)


def _client(handler) -> PandaScoreClient:
    return PandaScoreClient(
        base_url="https://api.pandascore.test",
        token="offline-test-token",
        transport=httpx.MockTransport(handler),
    )


def _row(team_id: int) -> dict[str, Any]:
    return {
        "id": team_id,
        "name": f" Team {team_id} ",
        "image_url": f"https://cdn.pandascore.test/{team_id}.png",
        "acronym": "ignored",
    }


def test_reader_fetches_complete_pages_serially_and_normalizes_optional_image_url() -> None:
    requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.path, dict(request.url.params)))
        if request.url.params["page"] == "1":
            return httpx.Response(
                200,
                json=[_row(team_id) for team_id in range(1, 101)],
                request=request,
            )
        row = _row(101)
        row["image_url"] = "  "
        return httpx.Response(200, json=[row], request=request)

    teams = asyncio.run(PandaScoreTeamDirectoryReader(_client(handler)).read_all())

    assert requests == [
        ("/dota2/teams", {"page": "1", "per_page": "100"}),
        ("/dota2/teams", {"page": "2", "per_page": "100"}),
    ]
    assert len(teams) == 101
    assert teams[0].source_id == 1
    assert teams[0].label == "Team 1"
    assert teams[-1].image_url is None


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (None, "invalid_team_row"),
        ({"id": True, "name": "Team"}, "invalid_team_id"),
        ({"id": 1, "name": "  "}, "invalid_team_name"),
        ({"id": 1, "name": "Team", "image_url": {}}, "invalid_team_image_url"),
    ],
)
def test_reader_fails_closed_on_invalid_required_metadata(row: object, reason: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[row], request=request)

    with pytest.raises(PandaScoreTeamDirectoryError) as raised:
        asyncio.run(PandaScoreTeamDirectoryReader(_client(handler)).read_all())

    assert raised.value.reason == reason


def test_reader_rejects_duplicates_and_propagates_page_failure() -> None:
    def duplicate_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_row(1), _row(1)], request=request)

    with pytest.raises(PandaScoreTeamDirectoryError) as raised:
        asyncio.run(PandaScoreTeamDirectoryReader(_client(duplicate_handler)).read_all())
    assert raised.value.reason == "duplicate_team_id"

    calls = 0

    def failing_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"error": "offline"}, request=request)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(PandaScoreTeamDirectoryReader(_client(failing_handler)).read_all())
    assert calls == 1
