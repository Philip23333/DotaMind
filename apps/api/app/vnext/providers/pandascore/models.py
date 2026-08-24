"""PandaScore-only response models.

These models intentionally stop at the provider boundary. Domain services
translate them into opaque references and normalized DotaMind DTOs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class PandaModel(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
    )


class PandaScoreLeague(PandaModel):
    provider_id: int = Field(alias="id", gt=0)
    name: str | None = None


class PandaScoreSeriesBrief(PandaModel):
    provider_id: int = Field(alias="id", gt=0)
    name: str | None = None
    full_name: str | None = None
    year: int | None = None
    season: str | None = None
    begin_at: datetime | None = None
    end_at: datetime | None = None
    league: PandaScoreLeague | None = None


class PandaScoreSeries(PandaScoreSeriesBrief):
    status: str | None = None
    tier: str | None = None
    region: str | None = None
    tournaments: list[dict[str, Any]] = Field(default_factory=list)


class PandaScoreTeam(PandaModel):
    provider_id: int = Field(alias="id", gt=0)
    name: str = Field(min_length=1)
    acronym: str | None = None
    slug: str | None = None
    image_url: str | None = None


class PandaScoreWinner(PandaModel):
    provider_id: int | None = Field(default=None, alias="id")
    name: str | None = None
    acronym: str | None = None


class PandaScoreOpponent(PandaModel):
    type: str | None = None
    opponent: PandaScoreTeam


class PandaScoreResult(PandaModel):
    score: int | None = None
    team_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("team_id", "winner_id"),
    )


class PandaScoreGame(PandaModel):
    provider_id: int = Field(alias="id", gt=0)
    position: int | None = None
    status: str | None = None
    scheduled_at: datetime | None = None
    begin_at: datetime | None = None
    end_at: datetime | None = None
    length: int | None = None
    match_id: int | None = None
    winner: PandaScoreWinner | None = None
    complete: bool | None = None
    detailed_stats: bool | None = None


class PandaScoreTournament(PandaModel):
    provider_id: int = Field(alias="id", gt=0)
    name: str | None = None
    begin_at: datetime | None = None
    end_at: datetime | None = None
    tier: str | None = None
    region: str | None = None
    series_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("serie_id", "series_id"),
    )


class PandaScoreMatch(PandaModel):
    provider_id: int = Field(alias="id", gt=0)
    name: str = Field(min_length=1)
    status: str = Field(min_length=1)
    scheduled_at: datetime | None = None
    begin_at: datetime | None = None
    end_at: datetime | None = None
    series_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("serie_id", "series_id"),
    )
    tournament_id: int | None = None
    number_of_games: int | None = None
    match_type: str | None = None
    opponents: list[PandaScoreOpponent] = Field(default_factory=list)
    results: list[PandaScoreResult] = Field(default_factory=list)
    games: list[PandaScoreGame] = Field(default_factory=list)
    series: PandaScoreSeriesBrief | None = Field(
        default=None,
        validation_alias=AliasChoices("serie", "series"),
    )
    league: PandaScoreLeague | None = None
    tournament: PandaScoreTournament | None = None
    complete: bool | None = None
    detailed_stats: bool | None = None
    live_supported: bool | None = None


__all__ = [
    "PandaScoreGame",
    "PandaScoreLeague",
    "PandaScoreMatch",
    "PandaScoreOpponent",
    "PandaScoreResult",
    "PandaScoreSeries",
    "PandaScoreSeriesBrief",
    "PandaScoreTeam",
    "PandaScoreTournament",
    "PandaScoreWinner",
]
