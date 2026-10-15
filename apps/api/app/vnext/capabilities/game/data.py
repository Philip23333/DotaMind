"""Closed recorded-game data contract, independent of provider response shapes."""

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_serializer,
    model_validator,
)

Number = StrictInt | StrictFloat
Scalar = StrictStr | Number | StrictBool | None
Side = Literal["radiant", "dire"]


class _Data(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class EntityData(_Data):
    id: StrictInt = Field(ge=0)
    name_zh: StrictStr | None = None
    name_en: StrictStr | None = None


class MissingData(_Data):
    path: str
    reason: str
    source_path: StrictStr | None = None
    source_value: Scalar = None

    @model_validator(mode="after")
    def paired_source_evidence(self) -> MissingData:
        present = self.model_fields_set & {"source_path", "source_value"}
        if present and (len(present) != 2 or not self.source_path):
            raise ValueError("Source evidence requires a path and corresponding scalar value")
        return self

    @model_serializer(mode="wrap")
    def serialize_evidence(self, handler):
        data = handler(self)
        for key in ("source_path", "source_value"):
            if key not in self.model_fields_set:
                data.pop(key, None)
        return data


class SourceConflict(_Data):
    paths: list[str]
    values: list[Scalar]

    @model_validator(mode="after")
    def corresponding_values(self) -> SourceConflict:
        if len(self.paths) < 2 or len(self.paths) != len(self.values):
            raise ValueError("Conflict paths and scalar values must correspond")
        return self


class CoverageData(_Data):
    missing: list[MissingData] = Field(default_factory=list)
    conflicts: list[SourceConflict] = Field(default_factory=list)


class TeamData(_Data):
    source_team_id: StrictInt | None = None
    name: str | None = None


class TeamsData(_Data):
    radiant: TeamData | None = None
    dire: TeamData | None = None


class ScoreData(_Data):
    radiant: StrictInt | None = None
    dire: StrictInt | None = None


class MatchData(_Data):
    match_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    duration_seconds: StrictInt | None = None
    game_winner: Side | None = None
    score: ScoreData
    teams: TeamsData
    # The competition field list has not been approved; no League body is copied.
    competition: None = None


class DraftAction(_Data):
    order: StrictInt | None = None
    action: Literal["ban", "pick"] | None = None
    hero: EntityData | None = None
    side: Side | None = None


class DraftData(_Data):
    picks_bans: list[DraftAction] | None = None


class PlayerIdentity(_Data):
    account_id: StrictInt | None = None
    player_slot: StrictInt | None = None
    hero: EntityData | None = None
    name: str | None = None
    personaname: str | None = None
    side: Side | None = None


class FinalStats(_Data):
    kills: StrictInt | None = None
    deaths: StrictInt | None = None
    assists: StrictInt | None = None
    level: StrictInt | None = None
    last_hits: StrictInt | None = None
    denies: StrictInt | None = None
    net_worth: Number | None = None
    hero_damage: Number | None = None
    tower_damage: Number | None = None
    hero_healing: Number | None = None


class MinuteData(_Data):
    time_seconds: StrictInt
    net_worth: Number | None = None
    earned_gold: Number | None = None
    experience: Number | None = None
    last_hits: Number | None = None
    denies: Number | None = None
    kills: StrictInt | None = None
    deaths: StrictInt | None = None


class PlayerData(_Data):
    identity: PlayerIdentity
    final_stats: FinalStats
    minute_timeline: list[MinuteData] | None = None


class EconomyData(_Data):
    time_seconds: list[StrictInt] | None = None
    radiant_gold_adv: list[Number | None] | None = None
    radiant_xp_adv: list[Number | None] | None = None


class FinalLoadout(_Data):
    inventory: list[EntityData | None] = Field(min_length=6, max_length=6)
    backpack: list[EntityData | None] = Field(min_length=3, max_length=3)
    item_neutral: EntityData | None = None
    item_neutral2: EntityData | None = None
    aghanims_scepter: Number | None = None
    aghanims_shard: Number | None = None
    moonshard: Number | None = None


class PurchaseEvent(_Data):
    time_seconds: Number | None = None
    item: EntityData | None = None
    charges: Number | None = None


class NeutralItemEvent(_Data):
    time_seconds: Number | None = None
    item: EntityData | None = None
    enhancement: EntityData | None = None


class PlayerBuild(_Data):
    player_slot: StrictInt | None = None
    final_loadout: FinalLoadout
    purchase_events: list[PurchaseEvent] | None = None
    ability_upgrade_sequence: list[EntityData] | None = None
    neutral_item_history: list[NeutralItemEvent] | None = None


class BuildsData(_Data):
    players: list[PlayerBuild] | None = None


class UnitData(_Data):
    kind: Literal[
        "hero", "lane_creep", "siege_creep", "neutral_creep", "tower", "barracks",
        "ancient", "building", "fountain", "courier", "ward", "roshan", "tormentor",
        "summoned_unit", "spell_unit", "roshans_banner",
    ] | None = None
    name_zh: StrictStr | None = None
    name_en: StrictStr | None = None
    hero_id: StrictInt | None = None
    side: Side | None = None
    lane: Literal["top", "mid", "bot"] | None = None
    tier: StrictInt | None = Field(default=None, ge=1, le=4)

    @model_validator(mode="after")
    def identities_are_typed(self) -> UnitData:
        if self.hero_id is not None and self.kind != "hero":
            raise ValueError("Only hero units have a hero ID")
        if self.tier is not None and self.kind != "tower":
            raise ValueError("Only tower units have a tower tier")
        return self


class HeroDeath(_Data):
    time_seconds: Number | None = None
    victim_player_slot: StrictInt | None = None
    killer_player_slot: StrictInt | None = None
    killer_unit: UnitData | None = None
    gold_lost: Number | None = None
    gold_fed: Number | None = None
    time_dead_seconds: Number | None = None


class BuybackEvent(_Data):
    time_seconds: Number | None = None
    player_slot: StrictInt | None = None


class ObjectiveEvent(_Data):
    time_seconds: Number | None = None
    type: Literal[
        "building_destruction", "roshan_kill", "aegis_pickup", "first_blood",
        "courier_death", "tormentor_kill",
    ] | None = None
    target_unit: UnitData | None = None
    actor_unit: UnitData | None = None
    player_slot: StrictInt | None = None
    victim_player_slot: StrictInt | None = None


class FirstBloodData(_Data):
    reported_time_seconds: Number | None = None
    objective_events: list[ObjectiveEvent] | None = None


class EventsData(_Data):
    hero_deaths: list[HeroDeath] | None = None
    buybacks: list[BuybackEvent] | None = None
    building_destructions: list[ObjectiveEvent] | None = None
    roshan_kills: list[ObjectiveEvent] | None = None
    aegis_pickups: list[ObjectiveEvent] | None = None
    first_blood: FirstBloodData
    other_objectives: list[ObjectiveEvent] | None = None


class TargetValue(_Data):
    target_hero: EntityData | None = None
    value: Number


class PlayerInteractions(_Data):
    player_slot: StrictInt | None = None
    kills_by_target: list[TargetValue] | None = None
    damage_by_target: list[TargetValue] | None = None
    healing_by_target: list[TargetValue] | None = None


class InteractionsData(_Data):
    players: list[PlayerInteractions] | None = None


class GameDetailData(_Data):
    match: MatchData
    draft: DraftData
    players: list[PlayerData] | None = None
    economy: EconomyData | None = None
    builds: BuildsData
    events: EventsData | None = None
    interactions: InteractionsData | None = None
    coverage: CoverageData
