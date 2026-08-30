"""Public and internal contracts for source-backed esports discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import Field

from app.vnext.artifacts.models import ArtifactRef
from app.vnext.domain.common.models import DomainModel

EsportsKind = Literal["league", "series", "tournament", "match", "team", "player"]
TimeScope = Literal["upcoming", "running", "past"]


class EsportsSearchRequest(DomainModel):
    """The complete model-facing esports discovery request."""

    kind: EsportsKind
    query: str | None = None
    teams: list[str] = Field(default_factory=list)
    time_scope: TimeScope | None = None
    limit: int = Field(default=10, ge=1, le=50)


@dataclass(frozen=True, slots=True)
class ProviderEntity:
    """One complete provider document before Artifact externalization."""

    source: str
    kind: EsportsKind
    source_identity: int | str
    fetched_at: datetime
    document: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderSearchBatch:
    """Internal provider output, including whether qualifying results may remain."""

    entities: list[ProviderEntity]
    truncated: bool = False


class EsportsSearchProvider(Protocol):
    """A source implementation for the broad esports-search capability."""

    async def search(self, request: EsportsSearchRequest) -> ProviderSearchBatch:
        """Return complete, source-shaped entities for one legal request."""


class SourceRecord(DomainModel):
    """A bounded observation and its complete stored source document."""

    source: str
    kind: EsportsKind
    artifact_ref: ArtifactRef
    facts: dict[str, Any] = Field(default_factory=dict)


class EsportsSearchWarning(DomainModel):
    """A stable warning about one record that could not be delivered."""

    code: Literal["artifact_externalization_failed"]
    source: str
    kind: EsportsKind


class EsportsSearchResult(DomainModel):
    """Bounded records from the configured esports-search implementation."""

    records: list[SourceRecord] = Field(default_factory=list)
    truncated: bool = False
    partial: bool = False
    warnings: list[EsportsSearchWarning] = Field(default_factory=list)


__all__ = [
    "EsportsKind",
    "EsportsSearchProvider",
    "EsportsSearchRequest",
    "EsportsSearchResult",
    "EsportsSearchWarning",
    "ProviderEntity",
    "ProviderSearchBatch",
    "SourceRecord",
    "TimeScope",
]
