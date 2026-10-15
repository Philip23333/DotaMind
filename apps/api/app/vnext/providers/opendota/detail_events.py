"""Typed event facts with exact unit lookup and scalar evidence for opaque encodings."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from app.vnext.capabilities.game.data import (
    BuybackEvent,
    CoverageData,
    EventsData,
    FirstBloodData,
    HeroDeath,
    ObjectiveEvent,
    SourceConflict,
)
from app.vnext.catalog import UnitCatalog

from .detail_entities import DetailEntities
from .detail_values import ABSENT, _missing, _rows, _value

_OBJECTIVE_TYPES = {
    "building_kill": ("building_destruction", "building_destructions"),
    "CHAT_MESSAGE_ROSHAN_KILL": ("roshan_kill", "roshan_kills"),
    "CHAT_MESSAGE_AEGIS": ("aegis_pickup", "aegis_pickups"),
    "CHAT_MESSAGE_FIRSTBLOOD": ("first_blood", "first_blood"),
    "CHAT_MESSAGE_COURIER_LOST": ("courier_death", "other_objectives"),
    "CHAT_MESSAGE_MINIBOSS_KILL": ("tormentor_kill", "other_objectives"),
}


def _known_slot(value: Any, slots: Counter) -> int | None:
    return value if type(value) is int and slots[value] == 1 else None


def _player_log(player: dict, key: str, index: int, path: str, coverage: CoverageData) -> Any:
    value = player.get(key)
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    _missing(coverage, path, f"Source players[{index}].{key} is unavailable or invalid")
    return None


def _opaque(row: dict, keys: tuple[str, ...], path: str, source_path: str,
            coverage: CoverageData) -> None:
    for key in keys:
        if key in row:
            _missing(coverage, path, f"Unverified source {key} encoding",
                     source_path=f"{source_path}.{key}", source_value=row[key])


def project_events(
    source: Mapping[str, Any], players: list[dict] | None,
    entities: DetailEntities, units: UnitCatalog, coverage: CoverageData,
) -> EventsData:
    slots = Counter(p["player_slot"] for p in players or [] if type(p.get("player_slot")) is int)
    by_hero: dict[int, list[int]] = {}
    for p in players or []:
        hero, slot = p.get("hero_id"), p.get("player_slot")
        if type(hero) is int and type(slot) is int:
            by_hero.setdefault(hero, []).append(slot)
    hero_sides = {}
    for p in players or []:
        hero, slot = p.get("hero_id"), p.get("player_slot")
        if (type(hero) is int and len(by_hero.get(hero, [])) == 1
                and _known_slot(slot, slots) is not None and type(p.get("isRadiant")) is bool):
            hero_sides[hero] = "radiant" if p["isRadiant"] else "dire"
    deaths: list[HeroDeath] = []
    buybacks: list[BuybackEvent] = []
    death_available = buyback_available = False
    if players is None:
        _missing(coverage, "events.hero_deaths", "Source players are unavailable")
        _missing(coverage, "events.buybacks", "Source players are unavailable")
    for i, player in enumerate(players or []):
        owner = player.get("player_slot")
        owner = owner if type(owner) is int else None
        death_log = _player_log(player, "deaths_log", i, "events.hero_deaths", coverage)
        if death_log is not None:
            death_available = True
            for j, row in enumerate(death_log):
                path = f"events.hero_deaths[{len(deaths)}]"
                source_path = f"players[{i}].deaths_log[{j}]"
                unit = entities.unit(row.get("key", ABSENT), f"{path}.killer_unit",
                                     f"{source_path}.key", coverage, units, hero_sides)
                owners = by_hero.get(unit.hero_id, []) if unit else []
                death = HeroDeath(
                    time_seconds=_value(row, "time", float, "", coverage, required=False),
                    victim_player_slot=owner, killer_unit=unit,
                    killer_player_slot=_known_slot(owners[0], slots) if len(owners) == 1 else None,
                    gold_lost=_value(row, "gold_lost", float, "", coverage, required=False),
                    gold_fed=_value(row, "gold_fed", float, "", coverage, required=False),
                    time_dead_seconds=_value(row, "time_dead", float, "", coverage, required=False),
                )
                if death.time_seconds is None:
                    _missing(coverage, "events.hero_deaths", "Some source event times are unknown")
                deaths.append(death)
        buyback_log = _player_log(player, "buyback_log", i, "events.buybacks", coverage)
        if buyback_log is not None:
            buyback_available = True
            for j, row in enumerate(buyback_log):
                path = f"events.buybacks[{len(buybacks)}]"
                source_path = f"players[{i}].buyback_log[{j}]"
                event = BuybackEvent(
                    time_seconds=_value(row, "time", float, "", coverage, required=False),
                    player_slot=owner,
                )
                _opaque(row, ("slot",), path, source_path, coverage)
                if event.time_seconds is None:
                    _missing(coverage, "events.buybacks", "Some source event times are unknown")
                if owner is not None and type(row.get("player_slot")) is int:
                    if row["player_slot"] != owner:
                        coverage.conflicts.append(SourceConflict(
                            paths=[f"players[{i}].player_slot", f"{source_path}.player_slot"],
                            values=[owner, row["player_slot"]],
                        ))
                elif "player_slot" in row:
                    _opaque(row, ("player_slot",), path, source_path, coverage)
                buybacks.append(event)
    if players == []:
        death_available = buyback_available = True

    objectives = _rows(source.get("objectives"), "events.objectives", coverage)
    groups: dict[str, list[ObjectiveEvent]] = {
        group: [] for _, group in _OBJECTIVE_TYPES.values()
    }
    reported = _value(source, "first_blood_time", float,
                      "events.first_blood.reported_time_seconds", coverage)
    for i, row in enumerate(objectives or []):
        code = row.get("type", ABSENT)
        kind, group = _OBJECTIVE_TYPES.get(code, (None, "other_objectives")) if type(
            code
        ) is str else (None, "other_objectives")
        target = "first_blood.objective_events" if group == "first_blood" else group
        path = f"events.{target}[{len(groups[group])}]"
        source_path = f"objectives[{i}]"
        if kind is None:
            _missing(coverage, f"{path}.type", "Objective type not mapped",
                     source_path=f"{source_path}.type", source_value=code)
        event = ObjectiveEvent(
            time_seconds=_value(row, "time", float, "", coverage, required=False), type=kind,
            target_unit=entities.unit(row.get("key", ABSENT), f"{path}.target_unit",
                                      f"{source_path}.key", coverage, units, hero_sides),
            actor_unit=entities.unit(row.get("unit", ABSENT), f"{path}.actor_unit",
                                     f"{source_path}.unit", coverage, units, hero_sides),
            player_slot=_known_slot(row.get("player_slot"), slots),
            victim_player_slot=_known_slot(row.get("victim_player_slot"), slots),
        )
        for key in ("player_slot", "victim_player_slot"):
            if key in row and getattr(event, key) is None:
                _missing(coverage, f"{path}.{key}", "Source player slot is not uniquely known",
                         source_path=f"{source_path}.{key}", source_value=row[key])
        _opaque(row, ("slot", "team", "killer", "value"), path, source_path, coverage)
        groups[group].append(event)
        if event.time_seconds is None:
            _missing(coverage, f"events.{target}", "Some source objective times are unknown")
        if group == "first_blood" and reported is not None and event.time_seconds is not None:
            if reported != event.time_seconds:
                coverage.conflicts.append(SourceConflict(
                    paths=["first_blood_time", f"{source_path}.time"],
                    values=[reported, event.time_seconds],
                ))
    return EventsData(
        hero_deaths=deaths if death_available else None,
        buybacks=buybacks if buyback_available else None,
        first_blood=FirstBloodData(reported_time_seconds=reported,
                                  objective_events=groups["first_blood"] if objectives is not None
                                  else None),
        **{key: value if objectives is not None else None for key, value in groups.items()
           if key != "first_blood"},
    )
