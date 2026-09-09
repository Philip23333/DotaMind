"""Semantic input and output models for esports player search."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .dtos import PlayerDTO, ResponseAnomaly


class PlayerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlayerSearchInput(PlayerModel):
    id: int | None = Field(
        default=None,
        gt=0,
        description="Exact player ID.",
    )
    team_id: int | None = Field(
        default=None,
        gt=0,
        description="Known team ID for roster discovery.",
    )
    name: str | None = Field(
        default=None,
        min_length=1,
        description="Professional player name or handle, such as 'Ame'.",
    )
    first_name: str | None = Field(
        default=None,
        min_length=1,
        description="Player's real first name.",
    )
    last_name: str | None = Field(
        default=None,
        min_length=1,
        description="Player's real last name.",
    )
    active: bool | None = Field(
        default=None,
        description="When true, restrict results to currently active players.",
    )
    page: int = Field(
        default=1,
        ge=1,
        description="Result page number.",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of players to return.",
    )


class PlayerSearchResult(PlayerModel):
    items: list[PlayerDTO]
    page: int
    limit: int
    anomalies: list[ResponseAnomaly] = Field(default_factory=list)


__all__ = [
    "PlayerDTO",
    "PlayerModel",
    "PlayerSearchInput",
    "PlayerSearchResult",
]
