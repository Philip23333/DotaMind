"""Semantic input and output models for esports series search."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
        description=(
            "Season or edition label to search for, "
            "such as '28' or 'Season 28'."
        ),
    )
    year: int | None = Field(
        default=None,
        ge=2000,
        le=2100,
        description="Calendar year of the series edition.",
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


class LeagueSummary(SeriesModel):
    id: int
    name: str | None = None


class SeriesItem(SeriesModel):
    id: int
    name: str | None = None
    full_name: str | None = None
    season: str | None = None
    year: int | None = None
    begin_at: datetime | None = None
    end_at: datetime | None = None
    league: LeagueSummary | None = None


class SeriesSearchResult(SeriesModel):
    items: list[SeriesItem]
    page: int
    limit: int


__all__ = [
    "LeagueSummary",
    "SeriesItem",
    "SeriesModel",
    "SeriesSearchInput",
    "SeriesSearchResult",
]
