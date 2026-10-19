"""Default data reports bind identity, time and metric before model analysis."""

from collections import Counter
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator

from .data import (
    BuybackEvent,
    CoverageData,
    DraftData,
    EntityData,
    FinalLoadout,
    FinalStats,
    HeroDeath,
    InventoryEvent,
    MatchData,
    NeutralItemEvent,
    Number,
    ObjectiveEvent,
    PlayerIdentity,
    SupportCount,
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


class MinutePlayer(_Data):
    identity: PlayerIdentity
    cumulative_gold_earned: Number | None = None
    level: int | None = None
    level_observed_at_seconds: Number | None = None
    known_kills: int | None = None
    known_deaths: int | None = None
    assists: int | None = None
    last_hits: Number | None = None
    denies: Number | None = None
    inventory_observation: InventoryEvent | None = None
    neutral_observation: NeutralItemEvent | None = None
    upgrades: UpgradeState = Field(default_factory=UpgradeState)
    support_known_counts: list[SupportSummary] = Field(default_factory=list)


class MinuteSnapshot(_TimedData):
    time_seconds: int
    players: list[MinutePlayer]


class FinalPlayer(_Data):
    identity: PlayerIdentity
    final_stats: FinalStats
    final_loadout: FinalLoadout | None = None
    support: list[SupportSummary] = Field(default_factory=list)
    ability_upgrade_events_path: str | None = None


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


class GameReport(_Data):
    schema_version: Literal[1] = 1
    match: MatchData
    draft: DraftData
    minute_snapshots: list[MinuteSnapshot]
    final_players: list[FinalPlayer]
    damage_matrix: list[DamageCell]
    events: list[ReportEvent]
    coverage: CoverageData
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Minute K/D are known event counts; minute assists remain unknown.",
            "Inventory and level are latest explicit observations, not exact minute frames.",
            "Final earned income is floor(GPM * formal duration / 60); not an exact final counter.",
            "Hero damage total and per-target damage have separate source scopes.",
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
    deaths = data.events.hero_deaths
    death_coverage = _unique(data.coverage.death_counts, "player_slot", slot)
    return MinutePlayer(
        identity=identity,
        cumulative_gold_earned=node.cumulative_gold_earned if node else None,
        level=level.level if level else None,
        level_observed_at_seconds=level.time_seconds if level else None,
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
        inventory_observation=inventory,
        neutral_observation=neutral,
        upgrades=states,
        support_known_counts=_support_counts(player, boundary),
    )


def _damage_cells(data):
    players = data.players or []
    hero_counts = Counter(p.identity.hero.id for p in players if p.identity.hero)
    rows = []
    for a in players:
        ai = _unique(data.interactions.players, "player_slot", a.identity.player_slot)
        for b in players:
            bi = _unique(data.interactions.players, "player_slot", b.identity.player_slot)
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
    minute = [
        MinuteSnapshot(time_seconds=t, players=[_minute_player(data, p, t) for p in players])
        for t in times
    ]
    final = []
    for p in players:
        build = _unique(data.builds.players, "player_slot", p.identity.player_slot)
        build_index = next((i for i, b in enumerate(data.builds.players or []) if b is build), None)
        final.append(
            FinalPlayer(
                identity=p.identity,
                final_stats=p.final_stats,
                final_loadout=build.final_loadout if build else None,
                support=[SupportSummary.from_count(t) for t in p.support.totals]
                if p.support
                else [],
                ability_upgrade_events_path=(
                    f"$.data.builds.players[{build_index}].ability_upgrade_events"
                    if build_index is not None
                    else None
                ),
            )
        )
    events = [
        ReportEvent(
            time_seconds=e.time_seconds,
            kind="hero_kill" if e.killer_player_slot is not None else "hero_death",
            fact=e,
        )
        for e in data.events.hero_deaths or []
    ]
    for key in (
        "buybacks",
        "building_destructions",
        "roshan_kills",
        "aegis_pickups",
        "other_objectives",
    ):
        for event in getattr(data.events, key) or []:
            events.append(
                ReportEvent(
                    time_seconds=event.time_seconds,
                    kind="buyback" if key == "buybacks" else event.type or "other_objective",
                    fact=event,
                )
            )
    events.sort(key=lambda e: (e.time_seconds is None, e.time_seconds or 0))
    return GameReport(
        match=data.match,
        draft=data.draft,
        minute_snapshots=minute,
        final_players=final,
        damage_matrix=_damage_cells(data),
        events=events,
        coverage=data.coverage,
    )
