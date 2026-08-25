"""Provider-neutral native Dota references used during artifact construction."""

from typing import Literal

from .common.models import DomainModel


class HeroRef(DomainModel):
    """Native Valve identity for one hero."""

    valve_hero_id: int


class ItemRef(DomainModel):
    """Native Valve identity for one item or neutral enhancement."""

    valve_item_id: int


class ItemSlotRef(DomainModel):
    """One inventory-like slot whose source-native item may be absent."""

    slot: int
    item: ItemRef | None


class AbilityUpgradeRef(DomainModel):
    """One source-native ability upgrade event."""

    valve_ability_id: int
    level: int
    time_seconds: int


class PlayerRef(DomainModel):
    """Native Steam identity when present in construction input."""

    steam_account_id: int | None


class TeamRef(DomainModel):
    """Native Valve team identity when present in construction input."""

    valve_team_id: int | None


class DraftEventRef(DomainModel):
    """One source-native draft event before canonical artifact construction."""

    order: int
    side: Literal["radiant", "dire"]
    hero: HeroRef
    is_pick: bool


__all__ = [
    "AbilityUpgradeRef",
    "DraftEventRef",
    "HeroRef",
    "ItemRef",
    "ItemSlotRef",
    "PlayerRef",
    "TeamRef",
]
