"""Provider-neutral PandaScore models used by the agentic tools."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PandaCompetition(BaseModel):
    pandascore_series_id: int
    name: str
    full_name: str | None = None
    year: int | None = None
    season: str | None = None
    league: dict[str, Any] | None = None
    tournaments: list[dict[str, Any]] = Field(default_factory=list)


class PandaTournamentStage(BaseModel):
    pandascore_tournament_id: int
    pandascore_series_id: int
    name: str
    begin_at: datetime | None = None
    end_at: datetime | None = None
    tier: str | None = None
    region: str | None = None


class PandaGameReference(BaseModel):
    pandascore_game_id: int
    pandascore_match_id: int
    position: int | None = None
    status: str | None = None
    begin_at: datetime | None = None
    end_at: datetime | None = None
    length_seconds: int | None = None
    winner_team_id: int | None = None
    # Free Fixture responses do not currently expose Valve's match id. Keep it
    # explicit and nullable instead of confusing PandaScore's match_id field.
    valve_match_id: int | None = None


class PandaMatchFixture(BaseModel):
    pandascore_match_id: int
    pandascore_series_id: int
    pandascore_tournament_id: int | None = None
    name: str
    status: Literal["not_started", "running", "finished", "canceled", "postponed"] | str
    scheduled_at: datetime | None = None
    begin_at: datetime | None = None
    end_at: datetime | None = None
    match_type: str | None = None
    number_of_games: int | None = None
    opponents: list[dict[str, Any]] = Field(default_factory=list)
    results: list[dict[str, Any]] = Field(default_factory=list)
    streams: list[dict[str, Any]] = Field(default_factory=list)
    tournament: PandaTournamentStage | None = None
    games: list[PandaGameReference] = Field(default_factory=list)


class PandaCoverage(BaseModel):
    fixture_available: bool = False
    detailed_stats: bool | None = None
    valve_match_id_available: bool = False
    source: str = "PandaScore Fixture API"


class ResolvedMatchGame(BaseModel):
    status: Literal["resolved", "ambiguous", "not_found", "pending_valve_match_id"]
    match: PandaMatchFixture | None = None
    game: PandaGameReference | None = None
    candidates: list[PandaMatchFixture] = Field(default_factory=list)
    coverage: PandaCoverage | None = None
