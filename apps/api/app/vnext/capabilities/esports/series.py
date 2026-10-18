"""Semantic input and output models for esports series search."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .dtos import ResponseAnomaly, SeriesDTO, TeamRefDTO


class SeriesModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeriesDateRange(SeriesModel):
    start: AwareDatetime = Field(description="Range start as an ISO 8601 timestamp with timezone.")
    end: AwareDatetime = Field(description="Range end as an ISO 8601 timestamp with timezone.")

    @model_validator(mode="after")
    def validate_order(self) -> SeriesDateRange:
        if self.start > self.end:
            raise ValueError("Range start must not be later than end")
        return self


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
    begin_at: SeriesDateRange | None = Field(
        default=None,
        description=(
            "Only return series whose start timestamp is within this range. "
            "Use for series starting in a time window; not all series active during it."
        ),
    )
    end_at: SeriesDateRange | None = Field(
        default=None,
        description=(
            "Only return series whose end timestamp is within this range. "
            "If begin_at is also supplied, both ranges must match."
        ),
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
    "SeriesDateRange",
    "SeriesDTO",
    "SeriesSearchInput",
    "SeriesSearchResult",
    "TeamRefDTO",
    "SeriesTeamsInput",
    "SeriesTeamsResult",
]
