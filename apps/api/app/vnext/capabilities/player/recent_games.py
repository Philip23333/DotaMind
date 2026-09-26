"""Contract for a bounded list of recent games for one Steam32 account."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictInt,
    field_validator,
    model_validator,
)

from .profile import SteamAccountId


class PlayerRecentGamesInput(BaseModel):
    """Request at most `limit` recent games for an exact Steam32 account."""

    model_config = ConfigDict(extra="forbid")

    steam_account_id: SteamAccountId = Field(
        description="Exact unsigned 32-bit Steam account ID; not a Steam64 ID or player name."
    )
    limit: Annotated[StrictInt, Field(ge=1, le=20)] = Field(
        default=5,
        description=(
            "Maximum number of recent games to return; this is not a history-completeness bound."
        ),
    )


class PlayerRecentGame(BaseModel):
    """One source game observation identified by its Valve game ID."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    valve_game_id: Annotated[StrictInt, Field(gt=0)] = Field(
        description="Valve single-game ID, usable as the input to GameDetailInput."
    )
    data: dict[str, JsonValue] = Field(
        description="Source business fields preserved as a JSON object without guessed schema."
    )


class PlayerRecentGamesResult(BaseModel):
    """Bounded recent-game observations; fewer than `limit` does not mean history is complete."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    steam_account_id: SteamAccountId
    provider: Literal["stratz"]
    retrieved_at: datetime = Field(description="Time this response was retrieved, with timezone.")
    limit: Annotated[StrictInt, Field(ge=1, le=20)]
    games: list[PlayerRecentGame] = Field(
        description=(
            "Source-confirmed recent games, latest first. The contract cannot prove ordering "
            "or completeness; the adapter must verify the provider semantics."
        )
    )

    @field_validator("retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_games(self) -> PlayerRecentGamesResult:
        if len(self.games) > self.limit:
            raise ValueError("games cannot exceed the requested limit")
        game_ids = [game.valve_game_id for game in self.games]
        if len(game_ids) != len(set(game_ids)):
            raise ValueError("games cannot contain duplicate valve_game_id values")
        return self
