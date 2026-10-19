"""Default data reports bind identity, time and metric before model analysis."""

from collections import Counter
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator

from .data import (
    AbilityUpgradeEvent,
    BuybackEvent,
    CoverageData,
    DraftData,
    EconomyMinute,
    EntityData,
    FinalLoadout,
    FinalStats,
    FirstBloodData,
    HeroDamageFrom,
    HeroDeath,
    InventoryEvent,
    InventorySlot,
    LevelEvent,
    MatchData,
    NeutralItemEvent,
    Number,
    ObjectiveEvent,
    PermanentUpgradeEvent,
    PlayerIdentity,
    PurchaseEvent,
    SupportCount,
    SupportEvent,
    TargetValue,
    _Data,
    _TimedData,
)


class UpgradeState(_Data):
    held_scepter: bool | None = None
    consumed_scepter: bool | None = None
    shard: bool | None = None
    consumed_moon_shard: bool | None = None


class SupportSummary(_Data):
    item: EntityData
    action: str
    count: int
    scope: Literal["source_total", "known_events"]

    @classmethod
    def from_count(cls, count):
        return cls(**count.model_dump(exclude={"source_paths"}))


class MinuteInventory(_Data):
    inventory: list[InventorySlot | None] = Field(min_length=6, max_length=6)
    backpack: list[InventorySlot | None] = Field(min_length=3, max_length=3)
    item_neutral: InventorySlot | None = None


class MinuteNeutral(_Data):
    item: EntityData | None = None
    enhancement: EntityData | None = None


class MinuteStatisticsPlayer(_Data):
    identity: PlayerIdentity
    cumulative_gold_earned: Number | None = None
    level: int | None = None
    known_kills: int | None = None
    known_deaths: int | None = None
    assists: int | None = None
    last_hits: Number | None = None
    denies: Number | None = None


class MinuteEquipmentPlayer(_Data):
    identity: PlayerIdentity
    inventory_observation: MinuteInventory | None = None
    neutral_observation: MinuteNeutral | None = None
    upgrades: UpgradeState = Field(default_factory=UpgradeState)


class MinuteSupportPlayer(_Data):
    identity: PlayerIdentity
    support_known_counts: list[SupportSummary] = Field(default_factory=list)


class StatisticsMinuteSnapshot(_TimedData):
    time_seconds: int
    players: list[MinuteStatisticsPlayer]


class EquipmentMinuteSnapshot(_TimedData):
    time_seconds: int
    players: list[MinuteEquipmentPlayer]


class SupportMinuteSnapshot(_TimedData):
    time_seconds: int
    players: list[MinuteSupportPlayer]


class FinalStatisticsPlayer(_Data):
    identity: PlayerIdentity
    final_stats: FinalStats


class FinalEquipmentPlayer(_Data):
    identity: PlayerIdentity
    final_loadout: FinalLoadout | None = None
    purchase_events_path: str | None = None
    ability_upgrade_events_path: str | None = None


class FinalSupportPlayer(_Data):
    identity: PlayerIdentity
    support: list[SupportSummary] = Field(default_factory=list)
    events_path: str | None = None


class ExperienceSample(_TimedData):
    time_seconds: int
    cumulative_experience: Number | None = None


class StatisticsHistory(_Data):
    identity: PlayerIdentity
    level_events: list[LevelEvent] | None = None
    experience_timeline: list[ExperienceSample] | None = None


class EquipmentHistory(_Data):
    identity: PlayerIdentity
    purchase_events: list[PurchaseEvent] | None = None
    inventory_events: list[InventoryEvent] | None = None
    ability_upgrade_events: list[AbilityUpgradeEvent] | None = None
    neutral_item_history: list[NeutralItemEvent] | None = None
    permanent_upgrade_events: list[PermanentUpgradeEvent] | None = None


class SupportHistory(_Data):
    identity: PlayerIdentity
    events: list[SupportEvent] | None = None
    totals: list[SupportCount] | None = None


class HeroRelations(_Data):
    identity: PlayerIdentity
    kills_by_target: list[TargetValue] | None = None
    healing_by_target: list[TargetValue] | None = None
    unmatched_damage_by_target: list[TargetValue] | None = None
    unmatched_damage_received_by_source: list[HeroDamageFrom] | None = None


class DamageCell(_Data):
    attacker_player_slot: int | None
    target_player_slot: int | None
    attacker_hero: EntityData | None
    target_hero: EntityData | None
    dealt: Number | None = None
    received_view: Number | None = None
    agreement: Literal["consistent", "conflict", "single_view", "unreported"]


class ReportEvent(_TimedData):
    kind: str
    fact: HeroDeath | ObjectiveEvent | BuybackEvent

    @field_validator("fact", mode="before")
    @classmethod
    def parse_event_kind(cls, value, info: ValidationInfo):
        if not isinstance(value, dict):
            return value
        kind = info.data.get("kind")
        model = (
            BuybackEvent
            if kind == "buyback"
            else (HeroDeath if kind in ("hero_kill", "hero_death") else ObjectiveEvent)
        )
        return model.model_validate(value)


class OverviewReport(_Data):
    title: Literal["比赛概况与选禁"] = "比赛概况与选禁"
    match: MatchData
    draft: DraftData


class PlayerStatisticsReport(_Data):
    title: Literal["玩家战绩与发育统计"] = "玩家战绩与发育统计"
    minute_snapshots: list[StatisticsMinuteSnapshot]
    final_players: list[FinalStatisticsPlayer]
    team_economy_timeline: list[EconomyMinute] | None
    player_histories: list[StatisticsHistory]


class EquipmentAndSkillsReport(_Data):
    title: Literal["装备、永久升级与技能成长"] = "装备、永久升级与技能成长"
    minute_snapshots: list[EquipmentMinuteSnapshot]
    final_players: list[FinalEquipmentPlayer]
    player_histories: list[EquipmentHistory]


class SupportContributionsReport(_Data):
    title: Literal["辅助物品使用、插眼与排眼"] = "辅助物品使用、插眼与排眼"
    minute_snapshots: list[SupportMinuteSnapshot]
    final_players: list[FinalSupportPlayer]
    player_histories: list[SupportHistory]


class HeroDamageReport(_Data):
    title: Literal["英雄间造成与承受伤害"] = "英雄间造成与承受伤害"
    matrix: list[DamageCell]
    player_relations: list[HeroRelations]


class EventsReport(_Data):
    title: Literal["击杀与重要目标事件"] = "击杀与重要目标事件"
    hero_kills_and_deaths: list[ReportEvent]
    buybacks: list[ReportEvent]
    building_destructions: list[ReportEvent]
    roshan_kills: list[ReportEvent]
    aegis_pickups: list[ReportEvent]
    other_objectives: list[ReportEvent]
    first_blood: FirstBloodData


class GameReport(_Data):
    schema_version: Literal[4] = 4
    overview: OverviewReport
    player_statistics: PlayerStatisticsReport
    equipment_and_skills: EquipmentAndSkillsReport
    support_contributions: SupportContributionsReport
    hero_damage: HeroDamageReport
    events: EventsReport
    coverage: CoverageData
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Minute K/D are known event counts; minute assists remain unknown.",
            "Minute states belong to the snapshot minute, using only observations at or before it; "
            "original observation times remain in report module histories. "
            "final_loadout uses explicit final fields.",
            "Final earned income is floor(GPM * formal duration / 60); not an exact final counter.",
            "Hero damage total and per-target damage have separate source scopes.",
            "Death loss sums known amounts even for unknown-time deaths; not a timed-death total.",
        ]
    )


def _latest(events, boundary):
    rows = [e for e in events or [] if e.time_seconds is not None and e.time_seconds <= boundary]
    if not rows:
        return None
    time = max(e.time_seconds for e in rows)
    candidates = [e for e in rows if e.time_seconds == time]
    return candidates[0] if all(e == candidates[0] for e in candidates) else None


def _unique(rows, attr, key):
    result = [row for row in rows or [] if getattr(row, attr) == key]
    return result[0] if key is not None and len(result) == 1 else None


def _support_counts(player, boundary):
    events = player.support.events if player.support else []
    keys = {(e.item.id, e.action): e.item for e in events if e.time_seconds is not None}
    counts = []
    for (item, action), entity in keys.items():
        known = [
            e
            for e in events
            if e.item.id == item
            and e.action == action
            and e.time_seconds is not None
            and e.time_seconds <= boundary
        ]
        paths = {(p.source, p.path): p for e in known for p in e.source_paths}
        counts.append(
            SupportSummary.from_count(
                SupportCount(
                    item=entity,
                    action=action,
                    count=len(known),
                    scope="known_events",
                    source_paths=list(paths.values()),
                )
            )
        )
    return counts


def _minute_player(data, player, boundary):
    identity = player.identity
    slot = identity.player_slot
    build = _unique(data.builds.players, "player_slot", slot)
    node = _unique(player.minute_timeline, "time_seconds", boundary)
    level = _latest(player.level_events, boundary)
    inventory = _latest(build.inventory_events, boundary) if build else None
    neutral = _latest(build.neutral_item_history, boundary) if build else None
    states = UpgradeState()
    if inventory:
        slots = inventory.inventory + inventory.backpack
        if all(s is not None for s in slots):
            states.held_scepter = any(s.item and s.item.id == 108 for s in slots)
    for event in build.permanent_upgrade_events or [] if build else []:
        if event.time_seconds is not None and event.time_seconds <= boundary:
            setattr(states, event.upgrade, True)
    deaths = data.events.hero_deaths if data.events else None
    death_coverage = _unique(data.coverage.death_counts, "player_slot", slot)
    statistics = MinuteStatisticsPlayer(
        identity=identity,
        cumulative_gold_earned=node.cumulative_gold_earned if node else None,
        level=level.level if level else None,
        known_kills=sum(
            e.killer_player_slot == slot
            for e in deaths
            if e.time_seconds is not None and e.time_seconds <= boundary
        )
        if deaths is not None
        and slot is not None
        and sum(p.identity.player_slot == slot for p in data.players or []) == 1
        else None,
        known_deaths=sum(
            e.victim_player_slot == slot
            for e in deaths
            if e.time_seconds is not None and e.time_seconds <= boundary
        )
        if deaths is not None
        and death_coverage is not None
        and death_coverage.known_time_deaths is not None
        else None,
        last_hits=node.last_hits if node else None,
        denies=node.denies if node else None,
    )
    equipment = MinuteEquipmentPlayer(
        identity=identity,
        inventory_observation=(
            MinuteInventory.model_validate(
                inventory.model_dump(exclude={"time_seconds", "time_label"})
            )
            if inventory
            else None
        ),
        neutral_observation=(
            MinuteNeutral.model_validate(neutral.model_dump(exclude={"time_seconds", "time_label"}))
            if neutral
            else None
        ),
        upgrades=states,
    )
    support = MinuteSupportPlayer(
        identity=identity,
        support_known_counts=_support_counts(player, boundary),
    )
    return statistics, equipment, support


def _damage_cells(data):
    players = data.players or []
    hero_counts = Counter(p.identity.hero.id for p in players if p.identity.hero)
    rows = []
    for a in players:
        ai = (
            _unique(data.interactions.players, "player_slot", a.identity.player_slot)
            if data.interactions
            else None
        )
        for b in players:
            bi = (
                _unique(data.interactions.players, "player_slot", b.identity.player_slot)
                if data.interactions
                else None
            )
            ah, bh = a.identity.hero, b.identity.hero
            dealt = (
                [v.value for v in ai.damage_by_target or [] if v.target_hero == bh]
                if ai and bh
                else []
            )
            received = (
                [v.value for v in bi.damage_received_by_source or [] if v.source_hero == ah]
                if bi and ah
                else []
            )
            unique = ah and bh and hero_counts[ah.id] == hero_counts[bh.id] == 1
            d = dealt[0] if unique and len(dealt) == 1 else None
            r = received[0] if unique and len(received) == 1 else None
            agreement = (
                ("consistent" if d == r else "conflict")
                if d is not None and r is not None
                else "single_view"
                if d is not None or r is not None
                else "unreported"
            )
            rows.append(
                DamageCell(
                    attacker_player_slot=a.identity.player_slot,
                    target_player_slot=b.identity.player_slot,
                    attacker_hero=ah,
                    target_hero=bh,
                    dealt=d,
                    received_view=r,
                    agreement=agreement,
                )
            )
    return rows


def build_game_report(data):
    """Construct only deterministic views; no source calls, scoring or prose generation."""
    players = data.players or []
    duration = data.match.duration_seconds
    times = (
        list(range(0, duration + 1, 60))
        if duration is not None
        else sorted({n.time_seconds for p in players for n in p.minute_timeline or []})
    )
    statistics_minutes, equipment_minutes, support_minutes = [], [], []
    for t in times:
        statistics, equipment, support = [], [], []
        for p in players:
            stats_row, equipment_row, support_row = _minute_player(data, p, t)
            statistics.append(stats_row)
            equipment.append(equipment_row)
            support.append(support_row)
        statistics_minutes.append(StatisticsMinuteSnapshot(time_seconds=t, players=statistics))
        equipment_minutes.append(EquipmentMinuteSnapshot(time_seconds=t, players=equipment))
        support_minutes.append(SupportMinuteSnapshot(time_seconds=t, players=support))
    final_statistics, final_equipment, final_support = [], [], []
    statistics_histories, equipment_histories, support_histories = [], [], []
    for player_index, p in enumerate(players):
        build = _unique(data.builds.players, "player_slot", p.identity.player_slot)
        history_path = f"$.report.equipment_and_skills.player_histories[{player_index}]"
        final_statistics.append(
            FinalStatisticsPlayer(identity=p.identity, final_stats=p.final_stats)
        )
        final_equipment.append(
            FinalEquipmentPlayer(
                identity=p.identity,
                final_loadout=build.final_loadout if build else None,
                purchase_events_path=(f"{history_path}.purchase_events" if build else None),
                ability_upgrade_events_path=(
                    f"{history_path}.ability_upgrade_events" if build else None
                ),
            )
        )
        final_support.append(
            FinalSupportPlayer(
                identity=p.identity,
                support=[SupportSummary.from_count(t) for t in p.support.totals]
                if p.support
                else [],
                events_path=(
                    f"$.report.support_contributions.player_histories[{player_index}].events"
                    if p.support
                    else None
                ),
            )
        )
        statistics_histories.append(
            StatisticsHistory(
                identity=p.identity,
                level_events=p.level_events,
                experience_timeline=[
                    ExperienceSample(
                        time_seconds=n.time_seconds, cumulative_experience=n.cumulative_experience
                    )
                    for n in p.minute_timeline
                ]
                if p.minute_timeline is not None
                else None,
            )
        )
        equipment_histories.append(
            EquipmentHistory(
                identity=p.identity,
                **{
                    field: getattr(build, field) if build else None
                    for field in (
                        "purchase_events",
                        "inventory_events",
                        "ability_upgrade_events",
                        "neutral_item_history",
                        "permanent_upgrade_events",
                    )
                },
            )
        )
        support_histories.append(
            SupportHistory(
                identity=p.identity,
                events=p.support.events if p.support else None,
                totals=p.support.totals if p.support else None,
            )
        )
    deaths = [
        ReportEvent(
            time_seconds=e.time_seconds,
            kind="hero_kill" if e.killer_player_slot is not None else "hero_death",
            fact=e,
        )
        for e in (data.events.hero_deaths if data.events else None) or []
    ]
    categories = {"hero_kills_and_deaths": deaths}
    for key in (
        "buybacks",
        "building_destructions",
        "roshan_kills",
        "aegis_pickups",
        "other_objectives",
    ):
        categories[key] = [
            ReportEvent(
                time_seconds=event.time_seconds,
                kind="buyback" if key == "buybacks" else event.type or "other_objective",
                fact=event,
            )
            for event in getattr(data.events, key, None) or []
        ]
    for rows in categories.values():
        rows.sort(key=lambda e: (e.time_seconds is None, e.time_seconds or 0))
    matrix = _damage_cells(data)
    relations = []
    for p in players:
        interaction = (
            _unique(data.interactions.players, "player_slot", p.identity.player_slot)
            if data.interactions
            else None
        )
        relations.append(
            HeroRelations(
                identity=p.identity,
                kills_by_target=interaction.kills_by_target if interaction else None,
                healing_by_target=interaction.healing_by_target if interaction else None,
                unmatched_damage_by_target=[
                    v
                    for v in interaction.damage_by_target
                    if not any(
                        c.attacker_player_slot == p.identity.player_slot
                        and c.target_hero == v.target_hero
                        and c.dealt == v.value
                        for c in matrix
                    )
                ]
                if interaction and interaction.damage_by_target is not None
                else None,
                unmatched_damage_received_by_source=[
                    v
                    for v in interaction.damage_received_by_source
                    if not any(
                        c.target_player_slot == p.identity.player_slot
                        and c.attacker_hero == v.source_hero
                        and c.received_view == v.value
                        for c in matrix
                    )
                ]
                if interaction and interaction.damage_received_by_source is not None
                else None,
            )
        )
    report = GameReport(
        overview=OverviewReport(match=data.match, draft=data.draft),
        player_statistics=PlayerStatisticsReport(
            minute_snapshots=statistics_minutes,
            final_players=final_statistics,
            team_economy_timeline=data.economy.minute_timeline if data.economy else None,
            player_histories=statistics_histories,
        ),
        equipment_and_skills=EquipmentAndSkillsReport(
            minute_snapshots=equipment_minutes,
            final_players=final_equipment,
            player_histories=equipment_histories,
        ),
        support_contributions=SupportContributionsReport(
            minute_snapshots=support_minutes,
            final_players=final_support,
            player_histories=support_histories,
        ),
        hero_damage=HeroDamageReport(matrix=matrix, player_relations=relations),
        events=EventsReport(
            **categories, first_blood=data.events.first_blood if data.events else FirstBloodData()
        ),
        coverage=data.coverage,
    )
    from .report_coverage import report_coverage

    report.coverage = report_coverage(data, report)
    return report
