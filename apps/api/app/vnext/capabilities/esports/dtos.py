"""Shared semantic esports entity DTOs."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ResponseAnomaly(BaseModel):
    """A model-visible anomaly observed while mapping one provider response."""

    model_config = ConfigDict(extra="forbid")

    path: str
    reason: str
    provider_id: int | None = None


class LeagueDTO(BaseModel):
    """Stable DotaMind representation of a PandaScore league identity."""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    slug: str | None = None
    image_url: str | None = None


class SeriesDTO(BaseModel):
    """Stable DotaMind representation of a PandaScore series edition."""

    model_config = ConfigDict(extra="forbid")

    id: int
    league_id: int

    name: str | None = None
    full_name: str | None = None

    year: int | None = None
    season: str | None = None

    begin_at: datetime | None = None
    end_at: datetime | None = None

    winner_id: int | None = None
    tier: str | None = None

    slug: str | None = None


class TeamRefDTO(BaseModel):
    """Stable lightweight team reference for embedded esports relations."""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str

    acronym: str | None = None
    location: str | None = None
    slug: str | None = None
    image_url: str | None = None


class PlayerRole(str, Enum):
    carry = "carry"
    mid = "mid"
    offlane = "offlane"
    soft_support = "soft_support"
    hard_support = "hard_support"


class CurrentRosterPlayerDTO(BaseModel):
    """A player in a Team's current membership snapshot."""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str

    active: bool
    role: tuple[PlayerRole, ...] | None = None

    first_name: str | None = None
    last_name: str | None = None
    nationality: str | None = None

    slug: str | None = None
    image_url: str | None = None


class TeamDTO(BaseModel):
    """Stable DotaMind representation of a Team and its current roster."""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str

    acronym: str | None = None
    location: str | None = None
    slug: str | None = None
    image_url: str | None = None

    current_roster: list[CurrentRosterPlayerDTO] = Field(default_factory=list)


class PlayerDTO(BaseModel):
    """Stable DotaMind representation of a current Player entity."""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str

    active: bool
    role: tuple[PlayerRole, ...] | None = None

    first_name: str | None = None
    last_name: str | None = None
    nationality: str | None = None

    slug: str | None = None
    image_url: str | None = None

    current_team: TeamRefDTO | None = None


class TournamentRosterPlayerDTO(BaseModel):
    """A player identity as captured in a tournament-context roster."""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str

    first_name: str | None = None
    last_name: str | None = None
    nationality: str | None = None

    slug: str | None = None


class TournamentParticipantDTO(BaseModel):
    """A team participating in a tournament and its expected roster."""

    model_config = ConfigDict(extra="forbid")

    team: TeamRefDTO
    expected_roster: list[TournamentRosterPlayerDTO] = Field(default_factory=list)


class TournamentDTO(BaseModel):
    """Stable DotaMind representation of a PandaScore tournament stage."""

    model_config = ConfigDict(extra="forbid")

    id: int
    series_id: int
    league_id: int

    name: str
    type: str | None = None

    country: str | None = None
    region: str | None = None

    begin_at: datetime | None = None
    end_at: datetime | None = None

    winner_id: int | None = None

    tier: str | None = None
    prizepool: str | None = None
    has_bracket: bool | None = None

    slug: str | None = None

    participants: list[TournamentParticipantDTO] = Field(default_factory=list)


class MatchParticipantDTO(BaseModel):
    """A team participating in a match and its provider-reported score."""

    model_config = ConfigDict(extra="forbid")

    team: TeamRefDTO
    score: int | None = None


class MatchGameDTO(BaseModel):
    """A single game within a match."""

    model_config = ConfigDict(extra="forbid")

    id: int
    position: int
    status: str

    begin_at: datetime | None = None
    end_at: datetime | None = None
    length: int | None = None

    winner_id: int | None = None

    complete: bool
    forfeit: bool


class MatchDTO(BaseModel):
    """Stable DotaMind representation of a PandaScore match."""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    slug: str | None = None

    status: str
    match_type: str | None = None
    number_of_games: int | None = None

    begin_at: datetime | None = None
    end_at: datetime | None = None

    scheduled_at: datetime | None = None
    original_scheduled_at: datetime | None = None

    league_id: int | None = None
    series_id: int | None = None
    tournament_id: int | None = None

    participants: list[MatchParticipantDTO] = Field(default_factory=list)

    winner_id: int | None = None
    winner: TeamRefDTO | None = None

    games: list[MatchGameDTO] = Field(default_factory=list)

    draw: bool
    forfeit: bool
    rescheduled: bool


__all__ = [
    "CurrentRosterPlayerDTO",
    "LeagueDTO",
    "MatchDTO",
    "MatchGameDTO",
    "MatchParticipantDTO",
    "PlayerDTO",
    "PlayerRole",
    "ResponseAnomaly",
    "SeriesDTO",
    "TeamRefDTO",
    "TeamDTO",
    "TournamentDTO",
    "TournamentParticipantDTO",
    "TournamentRosterPlayerDTO",
]
