"""Public contracts for detailed recorded-game retrieval."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.vnext.domain.common.models import DomainModel


class GameDetailRequest(DomainModel):
    """Request one recorded game by its canonical Valve game identity."""

    valve_game_id: int = Field(gt=0)


class GameDetailPayload(DomainModel):
    """Complete source-backed result before the tool applies its size boundary."""

    source: str
    valve_game_id: int = Field(gt=0)
    facts: dict[str, Any] = Field(default_factory=dict)


class GameDetailResult(DomainModel):
    """Inline facts or a bounded observation of one complete tool response."""

    source: str
    valve_game_id: int = Field(gt=0)
    artifact_ref: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)


__all__ = ["GameDetailPayload", "GameDetailRequest", "GameDetailResult"]
