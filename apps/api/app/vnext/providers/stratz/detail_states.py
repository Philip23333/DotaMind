"""Explicit timed level, ability-rank and permanent-upgrade source facts."""

from app.vnext.capabilities.game.data import (
    AbilityUpgradeEvent,
    CoverageGroup,
    LevelEvent,
    PermanentUpgradeEvent,
    SourcePath,
)
from app.vnext.providers.opendota.detail_values import ABSENT, _missing

UPGRADES = {108: "consumed_scepter", 609: "shard", 247: "consumed_moon_shard"}


def level_events(player, i, coverage):
    raw = (player.get("playbackData") or {}).get("playerUpdateLevelEvents")
    events = (
        None
        if not isinstance(raw, list)
        else [
            LevelEvent(time_seconds=e.get("time"), level=e.get("level"))
            for e in raw
            if type(e.get("level")) is int and e["level"] > 0
        ]
    )
    coverage.groups.append(
        CoverageGroup(
            path=f"players[{i}].level_events",
            status="unavailable" if events is None else "partial",
            source_paths=[
                SourcePath(
                    source="stratz", path=f"players[{i}].playbackData.playerUpdateLevelEvents"
                )
            ],
            reason="Explicit level observations; no initial state or updates inferred",
        )
    )
    return events


def ability_events(player, i, entities, coverage):
    raw = (player.get("playbackData") or {}).get("abilityLearnEvents")
    if not isinstance(raw, list):
        return None
    result = []
    for j, e in enumerate(raw):
        path = f"builds.players[{i}].ability_upgrade_events[{j}]"
        origin = f"players[{i}].playbackData.abilityLearnEvents[{j}]"
        key = e.get("abilityId", ABSENT)
        ability = entities.by_id(
            key if key != 0 else ABSENT,
            "ability",
            f"{path}.ability",
            f"{origin}.abilityId",
            coverage,
        )
        if key == 0:
            _missing(
                coverage,
                f"{path}.ability",
                "Unknown source ability ID",
                source_path=f"{origin}.abilityId",
                source_value=0,
            )
        rank = e.get("level")
        result.append(
            AbilityUpgradeEvent(
                time_seconds=e.get("time"),
                ability=ability,
                level=rank + 1 if ability is not None and type(rank) is int and rank >= 0 else None,
                is_talent=e.get("isTalent"),
                is_ultimate=e.get("isUltimate"),
            )
        )
    return result


def permanent_events(player, i, entities, coverage):
    raw = (player.get("stats") or {}).get("matchPlayerBuffEvent")
    result = None if not isinstance(raw, list) else []
    for j, row in enumerate(raw or []):
        item = row.get("itemId")
        if item not in UPGRADES:
            continue
        result.append(
            PermanentUpgradeEvent(
                time_seconds=row.get("time"),
                upgrade=UPGRADES[item],
                item=entities.by_id(
                    item,
                    "item",
                    f"builds.players[{i}].permanent_upgrade_events[{len(result)}].item",
                    f"players[{i}].stats.matchPlayerBuffEvent[{j}].itemId",
                    coverage,
                ),
                stack_count=row.get("stackCount"),
            )
        )
    coverage.groups.append(
        CoverageGroup(
            path=f"builds.players[{i}].permanent_upgrade_events",
            status="unavailable" if result is None else "partial",
            source_paths=[
                SourcePath(source="stratz", path=f"players[{i}].stats.matchPlayerBuffEvent")
            ],
            reason="Explicit permanent buffs only; absence does not establish inactive state",
        )
    )
    return result
