"""Provider-neutral competition DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.vnext.domain.common.models import CompetitionRef, DomainModel, Provenance

CompetitionStatus = Literal["upcoming", "running", "completed", "cancelled", "unknown"]


class Competition(DomainModel):
    ref: CompetitionRef
    name: str = Field(min_length=1)
    year: int | None = None
    status: CompetitionStatus = "unknown"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    tier: str | None = None
    region: str | None = None
    provenance: Provenance


class CompetitionCandidate(Competition):
    """A competition candidate; existence never implies unique resolution."""


class CompetitionSearchResult(DomainModel):
    status: Literal["unique", "ambiguous", "not_found"]
    query: str
    year: int | None = None
    candidate_count: int = Field(ge=0)
    candidates: list[CompetitionCandidate] = Field(default_factory=list)
    provenance: Provenance


__all__ = [
    "Competition",
    "CompetitionCandidate",
    "CompetitionSearchResult",
    "CompetitionStatus",
]
