"""Direct hero-target mappings; never aggregate nested ability/item target tables."""

from __future__ import annotations

from typing import Any

from app.vnext.capabilities.game.data import (
    CoverageData,
    InteractionsData,
    PlayerInteractions,
    TargetValue,
)

from .detail_entities import DetailEntities
from .detail_values import _is_number, _missing


def _targets(
    value: Any, path: str, source_path: str, entities: DetailEntities, coverage: CoverageData,
) -> list[TargetValue] | None:
    if not isinstance(value, dict):
        _missing(coverage, path, "Source hero-target map is unavailable or invalid")
        return None
    entries = [(key, amount) for key, amount in value.items()
               if type(key) is str and key.startswith("npc_dota_hero_")]
    if any(not _is_number(amount) for _, amount in entries):
        _missing(coverage, path, "Source hero-target map has an invalid amount")
        return None
    return [TargetValue(
        target_hero=entities.by_key(key, "hero", f"{path}[{i}].target_hero",
                                    f"{source_path}.{key}", coverage), value=amount,
    ) for i, (key, amount) in enumerate(entries)]


def project_interactions(
    players: list[dict] | None, entities: DetailEntities, coverage: CoverageData,
) -> InteractionsData:
    if players is None:
        _missing(coverage, "interactions.players", "Source players are unavailable")
        return InteractionsData()
    result = []
    for i, player in enumerate(players):
        slot = player.get("player_slot")
        result.append(PlayerInteractions(
            player_slot=slot if type(slot) is int else None,
            **{target: _targets(player.get(source), f"interactions.players[{i}].{target}",
                                f"players[{i}].{source}", entities, coverage)
               for target, source in (("kills_by_target", "killed"),
                                      ("damage_by_target", "damage"),
                                      ("healing_by_target", "healing"))},
        ))
    return InteractionsData(players=result)
