"""Canonical, provider-neutral data models for GameSummaryArtifact version 4."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _GameSummaryModel(BaseModel):
    """Reject fields outside the version 4 canonical artifact contract."""

    model_config = ConfigDict(extra="forbid")


class CatalogValue(_GameSummaryModel):
    """A catalog-backed value whose source identifier or name may be missing."""

    id: int | None = None
    name: str | None = None


class GameInfo(_GameSummaryModel):
    """Canonical native identity and recorded facts for the game."""

    valve_match_id: int
    start_time: datetime | None = None
    duration_seconds: int | None = None
    winner: Literal["radiant", "dire"] | None = None
    game_mode: CatalogValue = Field(default_factory=CatalogValue)
    lobby_type: CatalogValue = Field(default_factory=CatalogValue)


class TeamSummary(_GameSummaryModel):
    """Recorded team facts for one side of a game."""

    valve_team_id: int | None = None
    name: str | None = None
    score: int | None = None


class Teams(_GameSummaryModel):
    """Stable radiant and dire team structure."""

    radiant: TeamSummary = Field(default_factory=TeamSummary)
    dire: TeamSummary = Field(default_factory=TeamSummary)


class PlayerIdentity(_GameSummaryModel):
    """Persistent player identity facts, distinct from game placement."""

    steam_account_id: int | None = None
    registered_name: str | None = None
    persona_name: str | None = None


class Hero(_GameSummaryModel):
    """Canonical hero identity with available catalog-localized names."""

    id: int
    name_en: str | None = None
    name_zh: str | None = None


class PlayerStats(_GameSummaryModel):
    """Recorded scoreboard facts without derived analytics."""

    level: int | None = None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    last_hits: int | None = None
    denies: int | None = None


class PlayerEconomy(_GameSummaryModel):
    """Recorded economy facts without derived total gold or experience."""

    net_worth: int | None = None
    gold_per_min: int | None = None
    xp_per_min: int | None = None


class CanonicalItem(_GameSummaryModel):
    """One catalog-normalized item with available localized names."""

    id: int
    name_en: str | None = None
    name_zh: str | None = None


class ItemSlot(_GameSummaryModel):
    """One stable inventory or backpack slot, including empty slots."""

    slot: int
    id: int | None = None
    name_en: str | None = None
    name_zh: str | None = None


def _default_neutral_items() -> list[ItemSlot]:
    """Keep both canonical neutral positions observable when source data is absent."""

    return [ItemSlot(slot=0), ItemSlot(slot=1)]


class PlayerItems(_GameSummaryModel):
    """Inventory, backpack, and neutral item collections."""

    inventory: list[ItemSlot] = Field(default_factory=list)
    backpack: list[ItemSlot] = Field(default_factory=list)
    neutral_items: list[ItemSlot] = Field(
        default_factory=_default_neutral_items,
        validate_default=True,
    )

    @field_validator("neutral_items")
    @classmethod
    def _validate_neutral_slots(cls, value: list[ItemSlot]) -> list[ItemSlot]:
        if len(value) != 2 or [slot.slot for slot in value] != [0, 1]:
            raise ValueError("neutral_items must contain slots 0 and 1 in order")
        return value


class PurchaseEvent(_GameSummaryModel):
    """One purchase event in source order."""

    time_seconds: int
    item_id: int
    item_name_en: str | None = None
    item_name_zh: str | None = None


class AbilityUpgrade(_GameSummaryModel):
    """One skill-up event, rather than a hero ability catalog entry."""

    level: int | None = None
    time_seconds: int | None = None
    ability_id: int
    ability_name_en: str | None = None
    ability_name_zh: str | None = None


class PlayerGameSummary(_GameSummaryModel):
    """One player's canonical facts and game-specific placement."""

    identity: PlayerIdentity
    side: Literal["radiant", "dire"]
    player_slot: int
    hero: Hero
    stats: PlayerStats = Field(default_factory=PlayerStats)
    economy: PlayerEconomy = Field(default_factory=PlayerEconomy)
    items: PlayerItems = Field(default_factory=PlayerItems)
    purchase_history: list[PurchaseEvent] = Field(default_factory=list)
    ability_upgrades: list[AbilityUpgrade] = Field(default_factory=list)


class DraftEvent(_GameSummaryModel):
    """One pick or ban, with order retained in its separate collection."""

    order: int
    side: Literal["radiant", "dire"]
    hero_id: int
    hero_name_en: str | None = None
    hero_name_zh: str | None = None


class Draft(_GameSummaryModel):
    """Stable draft structure even when no draft data is available."""

    picks: list[DraftEvent] = Field(default_factory=list)
    bans: list[DraftEvent] = Field(default_factory=list)


class GameSummaryArtifactV4(_GameSummaryModel):
    """Provider-neutral canonical Dota facts for one game, schema version 4."""

    artifact_type: Literal["game_summary"] = "game_summary"
    schema_version: Literal["4"] = "4"
    game: GameInfo
    teams: Teams
    players: list[PlayerGameSummary] = Field(default_factory=list)
    draft: Draft = Field(default_factory=Draft)


__all__ = [
    "AbilityUpgrade",
    "CanonicalItem",
    "CatalogValue",
    "Draft",
    "DraftEvent",
    "GameInfo",
    "GameSummaryArtifactV4",
    "Hero",
    "ItemSlot",
    "PlayerEconomy",
    "PlayerGameSummary",
    "PlayerIdentity",
    "PlayerItems",
    "PlayerStats",
    "PurchaseEvent",
    "TeamSummary",
    "Teams",
]
