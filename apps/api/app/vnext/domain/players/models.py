"""Provider-neutral Player domain contracts."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from app.vnext.domain.common.models import DomainModel, PlayerRef, Provenance
from app.vnext.domain.teams.models import TeamIdentity


class PlayerCandidate(DomainModel):
    ref: PlayerRef
    name: str = Field(min_length=1)
    first_name: str | None = None
    last_name: str | None = None
    nationality: str | None = None
    role: str | None = None
    active: bool | None = None
    image_url: str | None = None
    current_team: TeamIdentity | None = None


class Player(DomainModel):
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
    current_team: TeamIdentity | None = None


class PlayerSearchResult(DomainModel):
    status: Literal["unique", "ambiguous", "not_found"]
    query: str
    candidate_count: int = Field(ge=0)
    candidates: list[PlayerCandidate] = Field(default_factory=list)
    provenance: Provenance


class PlayerGetResult(DomainModel):
    status: Literal["available", "not_found"]
    player: Player | None = None
    provenance: Provenance


__all__ = ["Player", "PlayerCandidate", "PlayerGetResult", "PlayerSearchResult"]
