from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.vnext.capabilities.esports.dtos import PlayerRole
from app.vnext.capabilities.esports.player import PlayerSearchInput
from app.vnext.providers.pandascore.client import PandaScoreClient
from app.vnext.providers.pandascore.player_adapter import PandaScorePlayerAdapter


def _adapter(handler) -> PandaScorePlayerAdapter:
    client = PandaScoreClient(
        base_url="https://api.pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    return PandaScorePlayerAdapter(client)


def _row(*, current_team: Any = None) -> dict[str, Any]:
    return {
        "id": 1669,
        "name": "Ame",
        "first_name": " Wang ",
        "last_name": " Chunyu ",
        "active": True,
        "nationality": " CN ",
        "role": " 1 / 2 ",
        "current_team": current_team,
        "slug": " ame ",
        "image_url": " https://example.test/ame.png ",
        "modified_at": "2026-09-01T00:00:00Z",
        "birthday": "2000-01-01",
        "current_videogame": {"id": 4, "name": "Dota 2"},
    }


def test_player_search_maps_all_semantic_fields_in_one_request() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        return httpx.Response(
            200,
            json=[
                _row(
                    current_team={
                        "id": 1647,
                        "name": "Team Liquid",
                        "acronym": "TL",
                        "location": " NL ",
                        "slug": "team-liquid",
                        "image_url": "https://example.test/liquid.png",
                        "modified_at": "2026-09-01T00:00:00Z",
                    }
                )
            ],
            request=request,
        )

    result = asyncio.run(
        _adapter(handler).search(
            PlayerSearchInput(
                id=1669,
                team_id=1647,
                name="Ame",
                first_name="Wang",
                last_name="Chunyu",
                active=True,
                page=2,
                limit=50,
            )
        )
    )

    assert calls == [
        (
            "/dota2/players",
            {
                "page": "2",
                "per_page": "50",
                "filter[id]": "1669",
                "filter[team_id]": "1647",
                "filter[active]": "true",
                "search[name]": "Ame",
                "search[first_name]": "Wang",
                "search[last_name]": "Chunyu",
            },
        )
    ]
    assert result.page == 2
    assert result.limit == 50


def test_player_normalization_projects_current_team_and_drops_provider_clutter() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                _row(
                    current_team={
                        "id": 1647,
                        "name": "Team Liquid",
                        "acronym": "TL",
                        "location": " NL ",
                        "slug": "team-liquid",
                        "image_url": " https://example.test/liquid.png ",
                    }
                )
            ],
            request=request,
        )

    item = asyncio.run(_adapter(handler).search(PlayerSearchInput())).items[0]

    assert item.model_dump(mode="json") == {
        "id": 1669,
        "name": "Ame",
        "first_name": "Wang",
        "last_name": "Chunyu",
        "active": True,
        "nationality": "CN",
        "role": ["carry", "mid"],
        "slug": "ame",
        "image_url": "https://example.test/ame.png",
        "current_team": {
            "id": 1647,
            "name": "Team Liquid",
            "acronym": "TL",
            "location": "NL",
            "slug": "team-liquid",
            "image_url": "https://example.test/liquid.png",
        },
    }
    assert not hasattr(item, "modified_at")
    assert not hasattr(item, "birthday")
    assert not hasattr(item, "current_videogame")


def test_player_without_current_team_is_valid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_row()], request=request)

    item = asyncio.run(_adapter(handler).search(PlayerSearchInput())).items[0]

    assert item.current_team is None


def test_player_role_mapping_supports_single_and_mixed_positions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert PandaScorePlayerAdapter._player_role(1) == (PlayerRole.carry,)
    assert PandaScorePlayerAdapter._player_role("1") == (PlayerRole.carry,)
    assert PandaScorePlayerAdapter._player_role(2) == (PlayerRole.mid,)
    assert PandaScorePlayerAdapter._player_role("1/2") == (
        PlayerRole.carry,
        PlayerRole.mid,
    )
    assert PandaScorePlayerAdapter._player_role(" 3 / 4 ") == (
        PlayerRole.offlane,
        PlayerRole.soft_support,
    )
    assert PandaScorePlayerAdapter._player_role(None) is None

    invalid_values = [0, 6, True, False, "", "carry", "mid", "1/6", "1/x"]
    with caplog.at_level("WARNING"):
        assert all(
            PandaScorePlayerAdapter._player_role(value) is None
            for value in invalid_values
        )
    for value in invalid_values:
        assert repr(value) in caplog.text


def test_player_active_is_required() -> None:
    row = _row()
    row.pop("active")

    with pytest.raises(KeyError, match="active"):
        PandaScorePlayerAdapter._normalize(row)


@pytest.mark.parametrize("value", [None, "invalid", 123])
def test_player_current_team_non_dict_defaults_to_none(value: Any) -> None:
    anomalies = []
    item = PandaScorePlayerAdapter._normalize(
        _row(current_team=value),
        path="provider.items[0]",
        anomalies=anomalies,
    )

    assert item.current_team is None
    if value is None:
        assert anomalies == []
    else:
        assert anomalies[0].path == "provider.items[0].current_team"
        assert anomalies[0].reason == "invalid current_team relation"


@pytest.mark.parametrize("missing", ["id", "name"])
def test_player_current_team_required_identity_is_strict(missing: str) -> None:
    current_team = {"id": 1647, "name": "Team Liquid"}
    current_team.pop(missing)

    anomalies = []
    item = PandaScorePlayerAdapter._normalize(
        _row(current_team=current_team),
        path="provider.items[0]",
        anomalies=anomalies,
    )

    assert item.current_team is None
    assert anomalies[0].path == "provider.items[0].current_team"
    assert anomalies[0].reason == "invalid current_team relation"
    assert anomalies[0].provider_id == (None if missing == "id" else 1647)
