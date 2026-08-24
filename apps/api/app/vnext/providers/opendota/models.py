"""OpenDota-only response models for league resolution and match detail."""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class OpenDotaModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class OpenDotaLeague(OpenDotaModel):
    provider_id: int = Field(
        gt=0,
        validation_alias=AliasChoices("leagueid", "league_id", "id"),
    )
    name: str = Field(min_length=1)
    tier: str | None = None


class OpenDotaTeam(OpenDotaModel):
    provider_id: int = Field(
        gt=0,
        validation_alias=AliasChoices("team_id", "id"),
    )
    name: str | None = None
    tag: str | None = None
    logo_url: str | None = None


class OpenDotaLeagueMatch(OpenDotaModel):
    provider_match_id: int = Field(gt=0, validation_alias="match_id")
    league_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("leagueid", "league_id"),
    )
    series_id: int | None = None
    series_type: int | None = None
    start_time: int | None = None
    duration: int | None = None
    radiant_team_id: int | None = None
    dire_team_id: int | None = None
    radiant_win: bool | None = None
    radiant_score: int | None = None
    dire_score: int | None = None


class OpenDotaMatchDetail(OpenDotaModel):
    provider_match_id: int = Field(gt=0, validation_alias="match_id")
    league_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("leagueid", "league_id"),
    )
    series_id: int | None = None
    start_time: int | None = None
    duration: int | None = None
    radiant_win: bool | None = None
    radiant_score: int | None = None
    dire_score: int | None = None
    radiant_team: dict[str, Any] | None = None
    dire_team: dict[str, Any] | None = None
    picks_bans: list[dict[str, Any]] = Field(default_factory=list)
    players: list[dict[str, Any]] = Field(default_factory=list)
    version: int | None = None
    replay_url: str | None = None
    game_mode: int | None = None
    lobby_type: int | None = None


__all__ = [
    "OpenDotaLeague",
    "OpenDotaLeagueMatch",
    "OpenDotaMatchDetail",
    "OpenDotaTeam",
]
