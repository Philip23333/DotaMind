"""Semantic input and output models for esports series search."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .dtos import ResponseAnomaly, SeriesDTO, TeamRefDTO


class SeriesModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeriesSearchInput(SeriesModel):
    id: int | None = Field(
        default=None,
        gt=0,
        description="Exact series ID.",
    )
    league_id: int | None = Field(
        default=None,
        gt=0,
        description="Only return series belonging to this league.",
    )
    name: str | None = Field(
        default=None,
        min_length=1,
        description="Series name to search for.",
    )
    season: str | None = Field(
        default=None,
        min_length=1,
        description=("Season or edition label to search for, such as '28' or 'Season 28'."),
    )
    year: int | None = Field(
        default=None,
        ge=2000,
        le=2100,
        description="Calendar year of the series edition.",
    )
    winner_id: int | None = Field(
        default=None,
        gt=0,
        description="Only return series won by this entity.",
    )
    tier: str | None = Field(
        default=None,
        min_length=1,
        description="Competition tier filter.",
    )
    page: int = Field(
        default=1,
        ge=1,
        description="Result page number.",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of series to return.",
    )


class SeriesSearchResult(SeriesModel):
    items: list[SeriesDTO]
    page: int
    limit: int
    anomalies: list[ResponseAnomaly] = Field(default_factory=list)


class SeriesTeamsInput(SeriesModel):
    series_id: int = Field(
        gt=0,
        description="Exact series ID whose participating teams should be returned.",
    )
    page: int = Field(
        default=1,
        ge=1,
        description="Result page number.",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of participating teams to return.",
    )


class SeriesTeamsResult(SeriesModel):
    items: list[TeamRefDTO]
    page: int
    limit: int
    anomalies: list[ResponseAnomaly] = Field(default_factory=list)


__all__ = [
    "SeriesModel",
    "SeriesDTO",
    "SeriesSearchInput",
    "SeriesSearchResult",
    "TeamRefDTO",
    "SeriesTeamsInput",
    "SeriesTeamsResult",
]
