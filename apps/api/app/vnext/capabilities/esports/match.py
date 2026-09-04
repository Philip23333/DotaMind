"""Semantic input and output models for esports match search."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class CompetitionSummary(MatchModel):
    id: int
    name: str | None = None


class SeriesSummary(MatchModel):
    id: int
    name: str | None = None
    full_name: str | None = None
    year: int | None = None


class TeamSummary(MatchModel):
    id: int
    name: str | None = None
    acronym: str | None = None


class MatchScore(MatchModel):
    team_id: int
    score: int


class MatchItem(MatchModel):
    id: int
    name: str | None = None
    status: str | None = None
    scheduled_at: datetime | None = None
    begin_at: datetime | None = None
    end_at: datetime | None = None
    match_type: str | None = None
    number_of_games: int | None = None
    league: CompetitionSummary | None = None
    series: SeriesSummary | None = None
    tournament: CompetitionSummary | None = None
    opponents: list[TeamSummary] = Field(default_factory=list)
    results: list[MatchScore] = Field(default_factory=list)
    winner_id: int | None = None


class MatchSearchResult(MatchModel):
    items: list[MatchItem]
    page: int
    limit: int


__all__ = [
    "CompetitionSummary",
    "MatchItem",
    "MatchScore",
    "MatchSearchInput",
    "MatchSearchResult",
    "MatchModel",
    "SeriesSummary",
    "TeamSummary",
]
