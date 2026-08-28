"""Provider-neutral construction input for a future game artifact builder."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common.models import DomainModel
from .refs import (
    AbilityUpgradeRef,
    DraftEventRef,
    HeroRef,
    ItemSlotRef,
    PlayerRef,
    PurchaseEventRef,
    TeamRef,
)


class GameContext(DomainModel):
    """Source-native game facts that may be absent before construction."""

    valve_match_id: int | None
    start_time: datetime | None
    duration_seconds: int | None
    radiant_win: bool | None
    game_mode_id: int | None
    lobby_type_id: int | None


class GameEventContext(DomainModel):
    """Readable canonical esports facts known before game construction."""

    league_name: str | None = None
    series_name: str | None = None
    series_year: int | None = None
    series_season: str | None = None
    tournament_name: str | None = None
    match_name: str | None = None
    match_number_of_games: int | None = None
    match_type: str | None = None
    game_position: int | None = None


class TeamContext(DomainModel):
    """One side's source-native identity and recorded game facts."""

    team_ref: TeamRef
    name: str | None
    score: int | None


class PlayerContext(DomainModel):
    """One player's source-native facts before catalog normalization."""

    player_ref: PlayerRef
    registered_name: str | None
    persona_name: str | None
    side: Literal["radiant", "dire"]
    player_slot: int
    hero_ref: HeroRef | None
    level: int | None = None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    last_hits: int | None = None
    denies: int | None = None
    net_worth: int | None = None
    gold_per_min: int | None = None
    xp_per_min: int | None = None
    item_slots: list[ItemSlotRef] = Field(default_factory=list)
    backpack_slots: list[ItemSlotRef] = Field(default_factory=list)
    neutral_items: list[ItemSlotRef] = Field(default_factory=list)
    purchase_history: list[PurchaseEventRef] = Field(default_factory=list)
    ability_upgrades: list[AbilityUpgradeRef] = Field(default_factory=list)


class GameConstructionContext(DomainModel):
    """Complete construction input; a later builder enforces artifact identity."""

    game: GameContext
    radiant_team: TeamContext
    dire_team: TeamContext
    players: list[PlayerContext] = Field(default_factory=list)
    draft_events: list[DraftEventRef] = Field(default_factory=list)
    event: GameEventContext | None = None


__all__ = [
    "GameConstructionContext",
    "GameEventContext",
    "GameContext",
    "PlayerContext",
    "TeamContext",
]
