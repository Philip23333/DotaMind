"""Models for PandaScore-to-OpenDota identity resolution."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ResolutionStatus = Literal[
    "resolved",
    "league_not_found",
    "ambiguous_league",
    "team_not_found",
    "ambiguous_team",
    "insufficient_signals",
    "not_found",
    "ambiguous_match",
]


class CrossSourceMapping(BaseModel):
    method: Literal["inferred_cross_source"] = "inferred_cross_source"
    confidence: Literal["high"] = "high"
    pandascore_match_id: int
    pandascore_game_id: int
    opendota_league_id: int
    opendota_series_id: int | None = None
    candidate_count: int
    matched_on: list[str] = Field(default_factory=list)
    start_time_delta_seconds: int
    duration_delta_seconds: int


class ResolvedValveMatch(BaseModel):
    valve_match_id: int
    opendota_league_id: int
    opendota_series_id: int | None = None


class TeamLeagueResolution(BaseModel):
    status: Literal["resolved", "ambiguous"]
    team: dict[str, Any] | None = None
    reason: str | None = None
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)


class CrossSourceResolution(BaseModel):
    status: ResolutionStatus
    match: ResolvedValveMatch | None = None
    mapping: CrossSourceMapping | None = None
    league: dict[str, Any] | None = None
    teams: list[dict[str, Any]] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    missing_signals: list[str] = Field(default_factory=list)
