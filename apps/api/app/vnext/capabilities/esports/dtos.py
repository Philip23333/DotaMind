"""Shared semantic esports entity DTOs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LeagueDTO(BaseModel):
    """Stable DotaMind representation of a PandaScore league identity."""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    slug: str | None = None
    image_url: str | None = None


__all__ = ["LeagueDTO"]
