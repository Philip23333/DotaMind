from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.integrations.valve.catalog_repository import DotaCatalogRepository
from app.vnext.capabilities.game import GameDetailInput, GameDetailResult
from app.vnext.capabilities.player import PlayerRecentGame, PlayerRecentGamesResult
from app.vnext.catalog import EntityNameResolver, UnitCatalog
from tests.vnext.test_game_detail_projection import project, record, source

NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)


def test_game_detail_input_uses_positive_strict_valve_game_id() -> None:
    assert GameDetailInput(valve_game_id=12345).valve_game_id == 12345
    for value in (0, -1, True, 12.0, "12345"):
        with pytest.raises(ValidationError):
            GameDetailInput(valve_game_id=value)
    with pytest.raises(ValidationError):
        GameDetailInput(valve_game_id=12345, game_id=12345)


def test_game_detail_requires_closed_governed_data_and_unique_label_versions() -> None:
    arguments = {
        "valve_game_id": 12345, "provider": "opendota", "retrieved_at": NOW,
        "catalog_version": EntityNameResolver(DotaCatalogRepository.load_default()).resolve_many(
            kind="hero", ids=[],
        ).catalog_version,
        "unit_mapping_version": UnitCatalog.load_default().version,
        "data": project(record(source(match_id=12345))),
    }
    result = GameDetailResult(**arguments)
    assert set(result.data.model_dump()) == {
        "match", "draft", "players", "economy", "builds", "events", "interactions", "coverage",
    }
    for data in ({}, {"match_id": 12345, "players": []}, {"raw": {"source": True}}):
        with pytest.raises(ValidationError):
            GameDetailResult(**{**arguments, "data": data})
    for key in ("catalog_version", "unit_mapping_version"):
        with pytest.raises(ValidationError):
            GameDetailResult(**{k: v for k, v in arguments.items() if k != key})
    with pytest.raises(ValidationError, match="timezone"):
        GameDetailResult(**{**arguments, "retrieved_at": datetime(2026, 9, 27)})
    with pytest.raises(ValidationError):
        GameDetailResult(**{**arguments, "provider": "unknown"})
    with pytest.raises(ValidationError):
        GameDetailResult(**arguments, raw={"source": True})


def test_recent_game_id_composes_directly_into_game_detail_input() -> None:
    recent = PlayerRecentGamesResult(
        steam_account_id=7,
        provider="stratz",
        retrieved_at=NOW,
        limit=5,
        games=[PlayerRecentGame(valve_game_id=987654, data={"mode": "ranked"})],
    )

    detail_input = GameDetailInput(valve_game_id=recent.games[0].valve_game_id)

    assert detail_input.valve_game_id == 987654
