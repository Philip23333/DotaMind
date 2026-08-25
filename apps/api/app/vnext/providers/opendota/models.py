"""OpenDota-only response models for league resolution and match detail."""

from __future__ import annotations

from typing import Any, Literal

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


class OpenDotaGameConstructionTeam(OpenDotaModel):
    """OpenDota team facts used only for construction input."""

    valve_team_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("team_id", "valve_team_id"),
    )
    name: str | None = None


class OpenDotaGameConstructionAbilityUpgrade(OpenDotaModel):
    """One explicitly timed and leveled OpenDota ability-upgrade event."""

    ability_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("ability_id", "ability"),
    )
    level: int | None = None
    time_seconds: int | None = Field(
        default=None,
        validation_alias=AliasChoices("time_seconds", "time"),
    )


class OpenDotaGameConstructionPlayer(OpenDotaModel):
    """OpenDota player fields needed for construction input only."""

    account_id: int | None = None
    registered_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("name", "registered_name"),
    )
    persona_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("personaname", "persona_name"),
    )
    player_slot: int = Field(ge=0)
    hero_id: int | None = None
    item_0: int | None = None
    item_1: int | None = None
    item_2: int | None = None
    item_3: int | None = None
    item_4: int | None = None
    item_5: int | None = None
    backpack_0: int | None = None
    backpack_1: int | None = None
    backpack_2: int | None = None
    item_neutral: int | None = None
    item_neutral2: int | None = None
    ability_upgrades: list[OpenDotaGameConstructionAbilityUpgrade] = Field(
        default_factory=list
    )


class OpenDotaGameConstructionDraftEvent(OpenDotaModel):
    """OpenDota draft event with source-native side and hero identifiers."""

    order: int
    team: Literal[0, 1]
    hero_id: int
    is_pick: bool


class OpenDotaGameConstructionMatch(OpenDotaModel):
    """OpenDota match fields needed for the construction pipeline."""

    match_id: int | None = None
    start_time: int | None = None
    duration: int | None = None
    radiant_win: bool | None = None
    game_mode: int | None = None
    lobby_type: int | None = None
    radiant_team: OpenDotaGameConstructionTeam | None = None
    dire_team: OpenDotaGameConstructionTeam | None = None
    radiant_score: int | None = None
    dire_score: int | None = None
    players: list[OpenDotaGameConstructionPlayer] = Field(default_factory=list)
    picks_bans: list[OpenDotaGameConstructionDraftEvent] = Field(default_factory=list)


__all__ = [
    "OpenDotaGameConstructionAbilityUpgrade",
    "OpenDotaGameConstructionDraftEvent",
    "OpenDotaGameConstructionMatch",
    "OpenDotaGameConstructionPlayer",
    "OpenDotaGameConstructionTeam",
    "OpenDotaLeague",
    "OpenDotaLeagueMatch",
    "OpenDotaMatchDetail",
    "OpenDotaTeam",
]
