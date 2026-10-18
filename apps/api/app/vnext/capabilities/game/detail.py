"""Governed recorded-game observations identified by their canonical Valve ID."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from app.vnext.catalog import EntityNameCatalogVersion

from .data import GameDetailData, Provider


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


class SourceRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retrieved_at: datetime

    @field_validator("retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value


class GameDetailResult(BaseModel):
    """Governed recorded-game facts with locally attributed bilingual labels."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    valve_game_id: Annotated[StrictInt, Field(gt=0)]
    provider: Literal["stratz"]
    retrieved_at: datetime = Field(description="Time this response was retrieved, with timezone.")
    sources: dict[Provider, SourceRead]
    catalog_version: EntityNameCatalogVersion
    unit_mapping_version: StrictStr = Field(min_length=1)
    data: GameDetailData = Field(description="Eight governed sections; no raw provider object.")

    @model_validator(mode="after")
    def consistent_provenance(self) -> GameDetailResult:
        if (
            self.provider not in self.sources
            or self.sources[self.provider].retrieved_at != self.retrieved_at
        ):
            raise ValueError("Primary source timestamp must match the result")
        for group in self.data.coverage.groups:
            if any(p.source not in self.sources for p in group.source_paths):
                raise ValueError("Coverage refers to a source that was not read")
        if self.data.events is not None:
            for field in (
                "hero_deaths",
                "buybacks",
                "building_destructions",
                "roshan_kills",
                "aegis_pickups",
                "other_objectives",
            ):
                for event in getattr(self.data.events, field) or []:
                    if not event.source_paths or any(
                        p.source not in self.sources for p in event.source_paths
                    ):
                        raise ValueError("Event refers to a source that was not read")
            for event in self.data.events.first_blood.objective_events or []:
                if not event.source_paths or any(
                    p.source not in self.sources for p in event.source_paths
                ):
                    raise ValueError("Event refers to a source that was not read")
        for conflict in self.data.coverage.conflicts:
            if any(source not in self.sources for source in conflict.sources):
                raise ValueError("Conflict refers to a source that was not read")
        return self

    @field_validator("retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value
