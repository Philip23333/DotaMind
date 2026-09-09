"""Shared semantic esports entity DTOs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LeagueDTO(BaseModel):
    """Stable DotaMind representation of a PandaScore league identity."""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    slug: str | None = None
    image_url: str | None = None


class SeriesDTO(BaseModel):
    """Stable DotaMind representation of a PandaScore series edition."""

    model_config = ConfigDict(extra="forbid")

    id: int
    league_id: int

    name: str | None = None
    full_name: str | None = None

    year: int | None = None
    season: str | None = None

    begin_at: datetime | None = None
    end_at: datetime | None = None

    winner_id: int | None = None
    tier: str | None = None

    slug: str | None = None


class TeamRefDTO(BaseModel):
    """Stable team identity used when a series lists its participants."""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str

    acronym: str | None = None
    location: str | None = None
    slug: str | None = None
    image_url: str | None = None


__all__ = ["LeagueDTO", "SeriesDTO", "TeamRefDTO"]
