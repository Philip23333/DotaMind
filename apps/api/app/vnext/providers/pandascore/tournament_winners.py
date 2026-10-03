"""Provider-only winner facts used to enrich homepage Series candidates."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TournamentWinnerSource(BaseModel):
    """The small set of source facts needed to resolve a Tournament winner."""

    model_config = ConfigDict(extra="forbid")

    id: int
    series_id: int
    name: str | None = None
    winner_id: int | None = None
    winner_type: str | None = None


__all__ = ["TournamentWinnerSource"]
