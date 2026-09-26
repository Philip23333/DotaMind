"""Contract for reading an existing OpenDota game-detail observation."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictInt, field_validator


class GameDetailInput(BaseModel):
    """Read an existing single-game detail by its Valve game ID."""

    model_config = ConfigDict(extra="forbid")

    valve_game_id: Annotated[StrictInt, Field(gt=0)] = Field(
        description="Positive Valve single-game ID, such as one returned by player.recent_games."
    )


class GameDetailResult(BaseModel):
    """Complete source JSON observation for an existing game, without summary conversion."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    valve_game_id: Annotated[StrictInt, Field(gt=0)]
    provider: Literal["opendota"]
    retrieved_at: datetime = Field(description="Time this response was retrieved, with timezone.")
    data: dict[str, JsonValue] = Field(
        description=(
            "Non-empty source business object preserved as JSON, including nested extensions, "
            "nulls, zeroes, and booleans."
        )
    )

    @field_validator("retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value

    @field_validator("data")
    @classmethod
    def require_nonempty_source_object(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if not value:
            raise ValueError("data must be a non-empty source JSON object")
        return value
