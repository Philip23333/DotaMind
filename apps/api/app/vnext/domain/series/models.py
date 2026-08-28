"""Provider-neutral series DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.vnext.domain.common.models import DomainModel, Provenance, SeriesRef

SeriesStatus = Literal["upcoming", "running", "completed", "cancelled", "unknown"]


class Series(DomainModel):
    ref: SeriesRef
    name: str = Field(min_length=1)
    year: int | None = None
    status: SeriesStatus = "unknown"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    tier: str | None = None
    region: str | None = None
    provenance: Provenance


class SeriesCandidate(Series):
    """A series candidate; existence never implies unique resolution."""


class SeriesSearchResult(DomainModel):
    status: Literal["unique", "ambiguous", "not_found"]
    query: str
    year: int | None = None
    candidate_count: int = Field(ge=0)
    candidates: list[SeriesCandidate] = Field(default_factory=list)
    provenance: Provenance


__all__ = [
    "Series",
    "SeriesCandidate",
    "SeriesSearchResult",
    "SeriesStatus",
]
