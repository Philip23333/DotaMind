"""Death, buyback and objective source records without speculative actor decoding."""

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

from .detail_values import _hero_id, _is_number, _missing, _rows, _value

_OBJECTIVE_TYPES = {
    "building_kill": "building_destructions",
    "CHAT_MESSAGE_ROSHAN_KILL": "roshan_kills",
    "CHAT_MESSAGE_AEGIS": "aegis_pickups",
    "CHAT_MESSAGE_FIRSTBLOOD": "first_blood",
}


def _scalar(value: Any) -> Any:
    return value if type(value) in (str, bool) or _is_number(value) else None


def _known_slot(value: Any, slots: Counter) -> int | None:
    return value if type(value) is int and slots[value] == 1 else None


def _player_log(player: dict, key: str, index: int, path: str, coverage: CoverageData) -> Any:
    value = player.get(key)
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    _missing(coverage, path, f"Source players[{index}].{key} is unavailable or invalid")
    return None


def project_events(
    source: Mapping[str, Any], players: list[dict] | None,
    hero_ids: Mapping[str, int], coverage: CoverageData,
) -> EventsData:
    slots = Counter(p["player_slot"] for p in players or [] if type(p.get("player_slot")) is int)
    by_hero: dict[int, list[int]] = {}
    for p in players or []:
        hero, slot = p.get("hero_id"), p.get("player_slot")
        if type(hero) is int and type(slot) is int:
            by_hero.setdefault(hero, []).append(slot)
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
            for row in death_log:
                key = _value(row, "key", str, "", coverage, required=False)
                hero = _hero_id(key, hero_ids)
                owners = by_hero.get(hero, [])
                death = HeroDeath(
                    time_seconds=_value(row, "time", float, "", coverage, required=False),
                    victim_player_slot=owner, killer_unit_key=key, killer_hero_id=hero,
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
                event = BuybackEvent(
                    time_seconds=_value(row, "time", float, "", coverage, required=False),
                    player_slot=owner, source_slot=_scalar(row.get("slot")),
                    source_player_slot=_scalar(row.get("player_slot")),
                )
                if event.time_seconds is None:
                    _missing(coverage, "events.buybacks", "Some source event times are unknown")
                if owner is not None and type(row.get("player_slot")) is int:
                    if row["player_slot"] != owner:
                        coverage.conflicts.append(SourceConflict(
                            paths=[f"players[{i}].player_slot",
                                   f"players[{i}].buyback_log[{j}].player_slot"],
                            values=[owner, row["player_slot"]],
                        ))
                buybacks.append(event)
    if players == []:
        death_available = buyback_available = True

    objectives = _rows(source.get("objectives"), "events.objectives", coverage)
    groups: dict[str, list[ObjectiveEvent]] = {
        name: [] for name in (*_OBJECTIVE_TYPES.values(), "other_objectives")
    }
    reported = _value(source, "first_blood_time", float,
                      "events.first_blood.reported_time_seconds", coverage)
    for i, row in enumerate(objectives or []):
        code = row.get("type")
        group = _OBJECTIVE_TYPES.get(code, "other_objectives") if type(code) is str else (
            "other_objectives"
        )
        event = ObjectiveEvent(
            time_seconds=_value(row, "time", float, "", coverage, required=False),
            source_type=_scalar(code),
            source_key=_scalar(row.get("key")),
            source_unit_key=_value(row, "unit", str, "", coverage, required=False),
            player_slot=_known_slot(row.get("player_slot"), slots),
            victim_player_slot=_known_slot(row.get("victim_player_slot"), slots),
            source_slot=_scalar(row.get("slot")),
            source_player_slot=_scalar(row.get("player_slot")),
            source_victim_player_slot=_scalar(row.get("victim_player_slot")),
            source_team=_scalar(row.get("team")), source_killer=_scalar(row.get("killer")),
            source_value=_scalar(row.get("value")),
        )
        groups[group].append(event)
        if event.time_seconds is None:
            _missing(coverage, f"events.{group}", "Some source objective times are unknown")
        if group == "first_blood" and reported is not None and event.time_seconds is not None:
            if reported != event.time_seconds:
                coverage.conflicts.append(SourceConflict(
                    paths=["first_blood_time", f"objectives[{i}].time"],
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
