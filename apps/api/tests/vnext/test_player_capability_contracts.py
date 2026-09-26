from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.vnext.capabilities.player import (
    PlayerProfileInput,
    PlayerProfileResult,
    PlayerRecentGame,
    PlayerRecentGamesInput,
    PlayerRecentGamesResult,
)

NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)


@pytest.mark.parametrize("steam_account_id", [1, 2**32 - 1])
def test_player_inputs_accept_steam32_boundaries(steam_account_id: int) -> None:
    profile_input = PlayerProfileInput(steam_account_id=steam_account_id)
    assert profile_input.steam_account_id == steam_account_id
    assert PlayerRecentGamesInput(steam_account_id=steam_account_id).limit == 5


@pytest.mark.parametrize("steam_account_id", [0, -1, 2**32, 76561198000000000, True, 12.0, "12"])
def test_player_inputs_reject_invalid_or_non_steam32_values(steam_account_id: object) -> None:
    with pytest.raises(ValidationError):
        PlayerProfileInput(steam_account_id=steam_account_id)


@pytest.mark.parametrize("limit", [1, 20])
def test_recent_games_limit_boundaries(limit: int) -> None:
    assert PlayerRecentGamesInput(steam_account_id=7, limit=limit).limit == limit


@pytest.mark.parametrize("limit", [0, 21, True, 1.0, "5"])
def test_recent_games_rejects_invalid_limit(limit: object) -> None:
    with pytest.raises(ValidationError):
        PlayerRecentGamesInput(steam_account_id=7, limit=limit)


def test_player_inputs_are_closed() -> None:
    with pytest.raises(ValidationError):
        PlayerProfileInput(steam_account_id=7, player_id=9)
    with pytest.raises(ValidationError):
        PlayerRecentGamesInput(steam_account_id=7, match_id=9)


def test_profile_presence_and_timezone_semantics() -> None:
    valid = PlayerProfileResult(
        steam_account_id=7,
        provider="stratz",
        retrieved_at=NOW,
        found=True,
        profile={"name": "player", "extension": {"rank": None, "active": False}},
    )
    assert valid.model_dump(mode="json")["profile"]["extension"] == {"rank": None, "active": False}
    assert PlayerProfileResult(
        steam_account_id=7,
        provider="stratz",
        retrieved_at=NOW,
        found=False,
        profile=None,
    ).found is False

    for found, profile in ((True, None), (True, {}), (False, {})):
        with pytest.raises(ValidationError):
            PlayerProfileResult(
                steam_account_id=7,
                provider="stratz",
                retrieved_at=NOW,
                found=found,
                profile=profile,
            )
    with pytest.raises(ValidationError):
        PlayerProfileResult(
            steam_account_id=7,
            provider="stratz",
            retrieved_at=NOW,
            found=False,
            profile=None,
            extra_field="not declared",
        )

    with pytest.raises(ValidationError, match="timezone"):
        PlayerProfileResult(
            steam_account_id=7,
            provider="stratz",
            retrieved_at=datetime(2026, 9, 27),
            found=False,
            profile=None,
        )
    with pytest.raises(ValidationError):
        PlayerProfileResult(
            steam_account_id=7,
            provider="opendota",
            retrieved_at=NOW,
            found=False,
            profile=None,
        )
    with pytest.raises(ValidationError):
        PlayerProfileResult(
            steam_account_id=7,
            provider="stratz",
            retrieved_at=NOW,
            found=1,
            profile={"name": "player"},
        )


def test_player_source_objects_accept_json_and_reject_non_json_values() -> None:
    game = PlayerRecentGame(
        valve_game_id=123,
        data={"nested": [None, 0, False, {"future_field": "kept"}]},
    )
    assert game.model_dump(mode="json")["data"] == {
        "nested": [None, 0, False, {"future_field": "kept"}]
    }
    for bad_value in (object(), float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            PlayerRecentGame(valve_game_id=123, data={"bad": bad_value})
    with pytest.raises(ValidationError):
        PlayerRecentGame(valve_game_id=123, data={}, source_extension=True)
    with pytest.raises(ValidationError):
        PlayerRecentGame(valve_game_id=123, data={1: "not a JSON object key"})


def test_recent_games_can_be_empty_but_must_obey_bound_and_unique_ids() -> None:
    empty = PlayerRecentGamesResult(
        steam_account_id=7,
        provider="stratz",
        retrieved_at=NOW,
        limit=2,
        games=[],
    )
    assert empty.games == []
    with pytest.raises(ValidationError):
        PlayerRecentGamesResult(
            steam_account_id=7,
            provider="stratz",
            retrieved_at=NOW.replace(tzinfo=None),
            limit=2,
            games=[],
        )
    with pytest.raises(ValidationError):
        PlayerRecentGamesResult(
            steam_account_id=7,
            provider="stratz",
            retrieved_at=NOW,
            limit=2,
            games=[],
            unexpected="field",
        )

    row = PlayerRecentGame(valve_game_id=123, data={"duration": 0})
    with pytest.raises(ValidationError, match="limit"):
        PlayerRecentGamesResult(
            steam_account_id=7,
            provider="stratz",
            retrieved_at=NOW,
            limit=1,
            games=[row, PlayerRecentGame(valve_game_id=124, data={"won": False})],
        )
    with pytest.raises(ValidationError, match="duplicate"):
        PlayerRecentGamesResult(
            steam_account_id=7,
            provider="stratz",
            retrieved_at=NOW,
            limit=2,
            games=[row, row],
        )
