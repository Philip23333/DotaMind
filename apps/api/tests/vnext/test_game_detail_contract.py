from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.vnext.capabilities.game import GameDetailInput, GameDetailResult
from app.vnext.capabilities.player import PlayerRecentGame, PlayerRecentGamesResult

NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)


def test_game_detail_input_uses_positive_strict_valve_game_id() -> None:
    assert GameDetailInput(valve_game_id=12345).valve_game_id == 12345
    for value in (0, -1, True, 12.0, "12345"):
        with pytest.raises(ValidationError):
            GameDetailInput(valve_game_id=value)
    with pytest.raises(ValidationError):
        GameDetailInput(valve_game_id=12345, game_id=12345)


def test_game_detail_preserves_nonempty_nested_json_source_object() -> None:
    result = GameDetailResult(
        valve_game_id=12345,
        provider="opendota",
        retrieved_at=NOW,
        data={"players": [{"purchase": None, "gold": 0, "radiant_win": False}]},
    )
    assert result.model_dump(mode="json")["data"] == {
        "players": [{"purchase": None, "gold": 0, "radiant_win": False}]
    }

    for data in ({}, {"unsupported": object()}, {"invalid_number": float("nan")}):
        with pytest.raises(ValidationError):
            GameDetailResult(
                valve_game_id=12345,
                provider="opendota",
                retrieved_at=NOW,
                data=data,
            )

    with pytest.raises(ValidationError, match="timezone"):
        GameDetailResult(
            valve_game_id=12345,
            provider="opendota",
            retrieved_at=datetime(2026, 9, 27),
            data={"players": []},
        )
    with pytest.raises(ValidationError):
        GameDetailResult(
            valve_game_id=12345,
            provider="stratz",
            retrieved_at=NOW,
            data={"players": []},
        )
    with pytest.raises(ValidationError):
        GameDetailResult(
            valve_game_id=12345,
            provider="opendota",
            retrieved_at=NOW,
            data={"players": []},
            unexpected="field",
        )


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
