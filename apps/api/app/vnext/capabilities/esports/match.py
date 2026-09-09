"""Semantic input and output models for esports match search."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .dtos import MatchDTO


class MatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MatchSearchInput(MatchModel):
    id: int | None = Field(default=None, gt=0, description="Exact match ID.")
    league_id: int | None = Field(
        default=None,
        gt=0,
        description="Only return matches belonging to this league.",
    )
    series_id: int | None = Field(
        default=None,
        gt=0,
        description="Only return matches belonging to this series.",
    )
    tournament_id: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Only return matches belonging to this tournament. "
            "Prefer this over series_id or league_id when known."
        ),
    )
    team_id: int | None = Field(
        default=None,
        gt=0,
        description="Only return matches involving this team.",
    )
    name: str | None = Field(
        default=None,
        min_length=1,
        description="Match name to search for. Prefer known entity IDs when available.",
    )
    status: str | None = Field(
        default=None,
        min_length=1,
        description="Match lifecycle status, such as finished or canceled.",
    )
    winner_id: int | None = Field(
        default=None,
        gt=0,
        description="Only return matches won by this entity.",
    )
    lifecycle: Literal["past", "running", "upcoming"] | None = Field(
        default=None,
        description="Restrict matches to past, currently running, or upcoming matches.",
    )
    sort: Literal["begin_at_asc", "begin_at_desc"] | None = Field(
        default=None,
        description="Order matches by actual start time.",
    )
    page: int = Field(default=1, ge=1, description="Result page number.")
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of matches to return.",
    )


class MatchSearchResult(MatchModel):
    items: list[MatchDTO]
    page: int
    limit: int


__all__ = [
    "MatchDTO",
    "MatchSearchInput",
    "MatchSearchResult",
    "MatchModel",
]
