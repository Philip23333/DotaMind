"""Provider-neutral match, game, and resolution result DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.vnext.domain.common.models import (
    CompetitionRef,
    DomainModel,
    GameRef,
    LeagueRef,
    MatchRef,
    Provenance,
    SeriesRef,
    Team,
    TeamRef,
    TournamentRef,
)

MatchStatus = Literal[
    "scheduled",
    "running",
    "finished",
    "cancelled",
    "postponed",
    "unknown",
]

TimeScope = Literal["upcoming", "recent", "running", "all"]

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


class LeagueSummary(DomainModel):
    ref: LeagueRef
    name: str = Field(min_length=1)


class CompetitionSummary(DomainModel):
    """Legacy compatibility DTO pending replacement by Series capability."""

    ref: CompetitionRef
    name: str = Field(min_length=1)
    year: int | None = None


class SeriesSummary(DomainModel):
    ref: SeriesRef
    name: str = Field(min_length=1)
    year: int | None = None
    season: str | None = None
    league: LeagueSummary | None = None


class TournamentSummary(DomainModel):
    ref: TournamentRef
    name: str | None = None
    series: SeriesSummary | None = None


class TeamScore(DomainModel):
    team: TeamRef
    score: int | None = None


class MatchResult(DomainModel):
    winner: TeamRef | None = None
    scores: list[TeamScore] = Field(default_factory=list)


class MatchSummary(DomainModel):
    ref: MatchRef
    name: str = Field(min_length=1)
    league: LeagueSummary | None = None
    series: SeriesSummary | None = None
    tournament: TournamentSummary | None = None
    competition: CompetitionSummary | None = None
    teams: list[Team] = Field(default_factory=list)
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: MatchStatus = "unknown"
    result: MatchResult | None = None
    games_count: int | None = None
    provenance: Provenance


class MatchCandidate(MatchSummary):
    """A search candidate; the candidate status is held by the search result."""


class CompetitionMatchesResult(DomainModel):
    status: Literal["ok", "not_found"]
    competition: CompetitionSummary
    time_scope: TimeScope
    candidate_count: int = Field(ge=0)
    matches: list[MatchSummary] = Field(default_factory=list)
    truncated: bool = False
    provenance: Provenance

    @property
    def candidates(self) -> list[MatchSummary]:
        """Natural alias for callers that treat a schedule as candidates."""

        return self.matches


class MatchSearchResult(DomainModel):
    status: Literal["unique", "ambiguous", "not_found"]
    query: str | None = None
    teams: list[str] = Field(default_factory=list)
    candidate_count: int = Field(ge=0)
    candidates: list[MatchCandidate] = Field(default_factory=list)
    provenance: Provenance


class ResolutionEvidence(DomainModel):
    start_time_delta_seconds: float | None = None
    duration_delta_seconds: float | None = None
    winner_consistent: bool | None = None


class ResolutionSummary(DomainModel):
    status: ResolutionStatus
    candidate_count: int = Field(ge=0)
    signals: list[str] = Field(default_factory=list)
    start_time_delta_seconds: float | None = None
    duration_delta_seconds: float | None = None
    winner_consistent: bool | None = None
    candidate_evidence: list[ResolutionEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DraftPick(DomainModel):
    order: int | None = None
    action: Literal["pick", "ban", "unknown"] = "unknown"
    side: Literal["radiant", "dire", "unknown"] = "unknown"


class ScoreboardRow(DomainModel):
    player_name: str | None = None
    side: Literal["radiant", "dire", "unknown"] = "unknown"
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    last_hits: int | None = None
    gold_per_min: int | None = None
    xp_per_min: int | None = None


class GameSummary(DomainModel):
    ref: GameRef
    position: int | None = None
    status: MatchStatus = "unknown"
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    winner: TeamRef | None = None
    provenance: Provenance


class GameDetail(GameSummary):
    valve_match_id: int | None = None
    detail_status: Literal["available", "fixture_only", "unavailable"] = "fixture_only"
    resolution: ResolutionSummary | None = None
    radiant_win: bool | None = None
    radiant_score: int | None = None
    dire_score: int | None = None
    draft: list[DraftPick] = Field(default_factory=list)
    scoreboard: list[ScoreboardRow] = Field(default_factory=list)
    coverage: list[str] = Field(default_factory=list)


Game = GameDetail


class MatchDetail(DomainModel):
    status: Literal["available", "unresolved", "detail_unavailable", "not_found"]
    match: MatchSummary | None = None
    games: list[GameDetail] = Field(default_factory=list)
    resolution: ResolutionSummary
    provenance: Provenance


__all__ = [
    "CompetitionMatchesResult",
    "CompetitionSummary",
    "DraftPick",
    "Game",
    "GameDetail",
    "GameSummary",
    "MatchCandidate",
    "MatchDetail",
    "MatchResult",
    "MatchSearchResult",
    "MatchStatus",
    "MatchSummary",
    "ResolutionEvidence",
    "ResolutionStatus",
    "ResolutionSummary",
    "ScoreboardRow",
    "TeamScore",
    "TimeScope",
]
