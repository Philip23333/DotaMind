"""Source-backed Artifact for one detailed recorded Dota game."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import ArtifactRef


class GameDetailArtifact(BaseModel):
    """Complete validated OpenDota-shaped facts for one Valve game ID."""

    model_config = ConfigDict(extra="forbid")

    artifact_type: Literal["game_detail"] = "game_detail"
    schema_version: Literal["1"] = "1"
    source: str
    valve_game_id: int = Field(gt=0)
    fetched_at: datetime
    facts: dict[str, Any] = Field(default_factory=dict)


def game_detail_artifact_ref(valve_game_id: int) -> ArtifactRef:
    """Build the canonical deterministic ArtifactRef for one Valve game."""

    if valve_game_id <= 0:
        raise ValueError("valve_game_id must be greater than zero")
    return ArtifactRef(
        id=f"game_detail:1:{valve_game_id}",
        artifact_type="game_detail",
        schema_version="1",
    )


__all__ = ["GameDetailArtifact", "game_detail_artifact_ref"]
