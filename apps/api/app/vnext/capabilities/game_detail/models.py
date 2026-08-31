"""Public contracts for detailed recorded-game retrieval."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.vnext.artifacts import ArtifactRef
from app.vnext.domain.common.models import DomainModel


class GameDetailRequest(DomainModel):
    """Request one recorded game by its canonical Valve game identity."""

    valve_game_id: int = Field(gt=0)


class GameDetailResult(DomainModel):
    """Bounded observation plus the complete detailed-game ArtifactRef."""

    source: str
    valve_game_id: int = Field(gt=0)
    artifact_ref: ArtifactRef
    facts: dict[str, Any] = Field(default_factory=dict)


__all__ = ["GameDetailRequest", "GameDetailResult"]
