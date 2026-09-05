"""Semantic input and output models for esports team search."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TeamModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TeamSearchInput(TeamModel):
    id: int | None = Field(
        default=None,
        gt=0,
        description="Exact team ID.",
    )
    name: str | None = Field(
        default=None,
        min_length=1,
        description="Team name, such as 'Team Liquid'.",
    )
    acronym: str | None = Field(
        default=None,
        min_length=1,
        description="Common competitive team abbreviation, such as 'LGD' or 'OG'.",
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
        description="Maximum number of teams to return.",
    )


class TeamItem(TeamModel):
    id: int
    name: str
    acronym: str | None = None
    location: str | None = None


class TeamSearchResult(TeamModel):
    items: list[TeamItem]
    page: int
    limit: int


__all__ = [
    "TeamItem",
    "TeamModel",
    "TeamSearchInput",
    "TeamSearchResult",
]
