"""Contract for reading an existing OpenDota game-detail observation."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from app.vnext.catalog import EntityNameCatalogVersion

from .data import GameDetailData


class GameDetailInput(BaseModel):
    """Read an existing single-game detail by its Valve game ID."""

    model_config = ConfigDict(extra="forbid")

    valve_game_id: Annotated[StrictInt, Field(gt=0)] = Field(
        description=(
            "Positive Valve single-game ID, such as one returned by player.recent_games "
            "or a resolved esports.game.resolve result; PandaScore Match, Series, and "
            "Game IDs are not valid here."
        )
    )


class GameDetailResult(BaseModel):
    """Governed recorded-game facts with locally attributed bilingual labels."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    valve_game_id: Annotated[StrictInt, Field(gt=0)]
    provider: Literal["opendota"]
    retrieved_at: datetime = Field(description="Time this response was retrieved, with timezone.")
    catalog_version: EntityNameCatalogVersion
    unit_mapping_version: StrictStr = Field(min_length=1)
    data: GameDetailData = Field(description="Eight governed sections; no raw provider object.")

    @field_validator("retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value
