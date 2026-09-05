"""Semantic input and output models for esports tournament search."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TournamentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TournamentSearchInput(TournamentModel):
    id: int | None = Field(
        default=None,
        gt=0,
        description="Exact tournament ID.",
    )
    series_id: int | None = Field(
        default=None,
        gt=0,
        description="Only return tournaments belonging to this series.",
    )
    name: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Tournament stage name to search for, "
            "such as 'Group Stage' or 'Playoffs'."
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
        description="Maximum number of tournaments to return.",
    )


class TournamentItem(TournamentModel):
    id: int
    name: str
    series_id: int | None = None
    begin_at: datetime | None = None
    end_at: datetime | None = None


class TournamentSearchResult(TournamentModel):
    items: list[TournamentItem]
    page: int
    limit: int


__all__ = [
    "TournamentItem",
    "TournamentModel",
    "TournamentSearchInput",
    "TournamentSearchResult",
]
