"""Thin source-attributed result contracts for esports discovery."""

from typing import Any

from pydantic import Field

from app.vnext.domain.common.models import DomainModel
from app.vnext.domain.source import SourceLocator


class SourceRecord(DomainModel):
    """Bounded source-shaped facts for one discoverable source object."""

    source: str
    kind: str
    locator: SourceLocator | None = None
    facts: dict[str, Any] = Field(default_factory=dict)


class EsportsSearchResult(DomainModel):
    """Bounded records from the configured esports-search implementation."""

    records: list[SourceRecord] = Field(default_factory=list)
    truncated: bool = False


__all__ = ["EsportsSearchResult", "SourceRecord"]
