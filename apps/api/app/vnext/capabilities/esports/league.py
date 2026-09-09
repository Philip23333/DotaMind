"""Semantic input and output models for esports league search."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .dtos import LeagueDTO, ResponseAnomaly


class LeagueModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LeagueSearchInput(LeagueModel):
    id: int | None = Field(
        default=None,
        gt=0,
        description="Exact league ID.",
    )
    name: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "League name to search for, such as "
            "'The International' or 'DreamLeague'."
        ),
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
        description="Maximum number of leagues to return.",
    )


class LeagueSearchResult(LeagueModel):
    items: list[LeagueDTO]
    page: int
    limit: int
    anomalies: list[ResponseAnomaly] = Field(default_factory=list)


__all__ = [
    "LeagueDTO",
    "LeagueModel",
    "LeagueSearchInput",
    "LeagueSearchResult",
]
