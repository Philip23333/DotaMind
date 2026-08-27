"""Provider-neutral Team domain contracts."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from app.vnext.domain.common.models import DomainModel, PlayerRef, Provenance, TeamRef


class TeamIdentity(DomainModel):
    ref: TeamRef
    name: str = Field(min_length=1)
    acronym: str | None = None
    logo_url: str | None = None


class TeamCandidate(TeamIdentity):
    location: str | None = None


class TeamPlayer(DomainModel):
    ref: PlayerRef
    name: str = Field(min_length=1)
    first_name: str | None = None
    last_name: str | None = None
    nationality: str | None = None
    role: str | None = None
    active: bool | None = None
    birthday: date | None = None
    birth_year: int | None = None
    hometown: str | None = None
    image_url: str | None = None


class Team(DomainModel):
    ref: TeamRef
    name: str = Field(min_length=1)
    acronym: str | None = None
    location: str | None = None
    logo_url: str | None = None
    players: list[TeamPlayer] = Field(default_factory=list)


class TeamSearchResult(DomainModel):
    status: Literal["unique", "ambiguous", "not_found"]
    query: str
    candidate_count: int = Field(ge=0)
    candidates: list[TeamCandidate] = Field(default_factory=list)
    provenance: Provenance


class TeamGetResult(DomainModel):
    status: Literal["available", "not_found"]
    team: Team | None = None
    provenance: Provenance


__all__ = [
    "Team",
    "TeamCandidate",
    "TeamGetResult",
    "TeamIdentity",
    "TeamPlayer",
    "TeamSearchResult",
]
