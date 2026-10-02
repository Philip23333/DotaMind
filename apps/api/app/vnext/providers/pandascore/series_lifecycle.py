"""Provider-only models for lifecycle-based PandaScore series reads."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.vnext.capabilities.esports.dtos import ResponseAnomaly, SeriesDTO


class SeriesLifecycleItem(SeriesDTO):
    """A Series source item with its provider-declared winner entity type."""

    winner_type: str | None = None


class SeriesLifecycleResult(BaseModel):
    """One bounded lifecycle page and any rows that could not be mapped."""

    model_config = ConfigDict(extra="forbid")

    items: list[SeriesLifecycleItem]
    page: int
    limit: int
    anomalies: list[ResponseAnomaly] = Field(default_factory=list)


__all__ = ["SeriesLifecycleItem", "SeriesLifecycleResult"]
