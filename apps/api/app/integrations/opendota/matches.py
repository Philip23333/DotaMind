"""OpenDota match detail access and deterministic normalization."""

from __future__ import annotations

from typing import Any

from app.integrations.opendota.transport import OpenDotaTransport
from app.integrations.valve.catalog_repository import (
    CatalogLookupError,
    DotaCatalogRepository,
    load_default_catalog_repository,
)

_ATTRIBUTE_BONUS_ABILITY_ID = 730
_ATTRIBUTE_BONUS_INTERNAL_NAME = "special_bonus_attributes"
_ATTRIBUTE_BONUS_NAME_EN = "Attributes +2"
_ATTRIBUTE_BONUS_NAME_ZH = "全属性 +2"
_TALENT_PLAYER_LEVELS = (10, 15, 20, 25)


class OpenDotaMatches:
    def __init__(self, transport: OpenDotaTransport) -> None:
        self.transport = transport

    async def get_match(self, valve_match_id: int) -> dict[str, Any]:
        data = await self.transport.get(
            f"match_{valve_match_id}",
            f"/matches/{valve_match_id}",
        )
        if not isinstance(data, dict):
            raise ValueError("OpenDota match response must be an object")
        return data


def normalize_parse_coverage(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "has_api": True,
        "has_gcdata": bool(match.get("radiant_gold_adv") or match.get("players")),
        "has_parsed": bool(match.get("players")) and match.get("version") is not None,
        "has_archive": bool(match.get("replay_url")),
        "parse_version": match.get("version"),
    }


def normalize_match_summary(match: dict[str, Any], valve_match_id: int) -> dict[str, Any]:
    catalog = load_default_catalog_repository()
    players = match.get("players") if isinstance(match.get("players"), list) else []
    normalized_players = [
        _normalize_player(player, catalog) for player in players if isinstance(player, dict)
    ]
    return {
        "valve_match_id": valve_match_id,
        "match_id": valve_match_id,
        "start_time": match.get("start_time"),
        "duration": match.get("duration"),
        "radiant_win": match.get("radiant_win"),
        "radiant_score": match.get("radiant_score"),
        "dire_score": match.get("dire_score"),
        "teams": {
            "radiant": match.get("radiant_team"),
            "dire": match.get("dire_team"),
        },
        "league_id": match.get("leagueid", match.get("league_id")),
        "series_id": match.get("series_id"),
        "cluster": match.get("cluster"),
        "game_mode": match.get("game_mode"),
        "lobby_type": match.get("lobby_type"),
        "players": normalized_players,
        "replay_url": match.get("replay_url"),
        "parse_coverage": normalize_parse_coverage(match),
        "catalog_snapshot": catalog.snapshot_metadata(),
    }


def normalize_match_draft(match: dict[str, Any], valve_match_id: int) -> dict[str, Any]:
    catalog = load_default_catalog_repository()
    raw = match.get("picks_bans")
    draft: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for index, row in enumerate(raw):
            if not isinstance(row, dict) or row.get("hero_id") is None:
                continue
            draft.append(
                {
                    "order": row.get("order", index),
                    "action": "pick" if row.get("is_pick") is True else "ban",
                    "team": "radiant" if row.get("team", 0) == 0 else "dire",
                    "hero_id": row.get("hero_id"),
                    **_hero_catalog_fields(row.get("hero_id"), catalog),
                }
            )
    timings = match.get("picks_bans_timing")
    return {
        "match": {"valve_match_id": valve_match_id, "match_id": valve_match_id},
        "draft": draft,
        "draft_timings": timings if isinstance(timings, list) else [],
        "coverage": normalize_parse_coverage(match),
        "catalog_snapshot": catalog.snapshot_metadata(),
    }


def _normalize_player(player: dict[str, Any], catalog: DotaCatalogRepository) -> dict[str, Any]:
    final_items = {
        "item_0": player.get("item_0"),
        "item_1": player.get("item_1"),
        "item_2": player.get("item_2"),
        "item_3": player.get("item_3"),
        "item_4": player.get("item_4"),
        "item_5": player.get("item_5"),
    }
    backpack = {
        "item_0": player.get("backpack_0"),
        "item_1": player.get("backpack_1"),
        "item_2": player.get("backpack_2"),
    }
    ability_upgrade_sequence = _normalize_ability_upgrades(
        player.get("ability_upgrades_arr"), catalog
    )
    return {
        "player_slot": player.get("player_slot"),
        "account_id": player.get("account_id"),
        "name": player.get("name", player.get("personaname")),
        "personaname": player.get("personaname", player.get("name")),
        "hero_id": player.get("hero_id"),
        **_hero_catalog_fields(player.get("hero_id"), catalog),
        "kills": player.get("kills"),
        "deaths": player.get("deaths"),
        "assists": player.get("assists"),
        "last_hits": player.get("last_hits"),
        "denies": player.get("denies"),
        "gpm": player.get("gold_per_min", player.get("gpm")),
        "xpm": player.get("xp_per_min", player.get("xpm")),
        "level": player.get("level"),
        "net_worth": player.get("net_worth"),
        "hero_damage": player.get("hero_damage"),
        "tower_damage": player.get("tower_damage"),
        "hero_healing": player.get("hero_healing"),
        "final_items": final_items,
        "final_item_details": _item_catalog_details(final_items, catalog),
        "backpack": backpack,
        "backpack_item_details": _item_catalog_details(backpack, catalog),
        "neutral_item": player.get("item_neutral"),
        "neutral_item_detail": _item_catalog_field(player.get("item_neutral"), catalog),
        "purchase_timeline": _normalize_purchase_timeline(player.get("purchase_log"), catalog),
        "inventory": _normalize_inventory(player, catalog),
        "ability_upgrade_sequence": ability_upgrade_sequence,
        "talent_selections": _normalize_talent_selections(ability_upgrade_sequence),
    }


def _normalize_purchase_timeline(
    purchase_log: Any, catalog: DotaCatalogRepository
) -> list[dict[str, Any]]:
    if not isinstance(purchase_log, list):
        return []
    timeline: list[dict[str, Any]] = []
    for row in purchase_log:
        if not isinstance(row, dict):
            continue
        raw_key = row.get("key")
        item = _item_reference(raw_key, catalog)
        item_internal_name, is_terminal_item = _catalog_item_progress_fields(item, catalog)
        event = {
            "time_seconds": row.get("time"),
            "item_key": raw_key,
            "item_id": item.get("item_id") if item else None,
            "item_name_en": item.get("item_name_en") if item else None,
            "item_name_zh": item.get("item_name_zh") if item else None,
            "item_internal_name": item_internal_name,
            "is_terminal_item": is_terminal_item,
            "item_catalog_status": item.get("item_catalog_status")
            if item
            else "not_found",
            "item_image_path": item.get("item_image_path") if item else None,
        }
        if "charges" in row:
            event["charges"] = row.get("charges")
        timeline.append(event)
    return timeline


def _catalog_item_progress_fields(
    item: dict[str, Any] | None, catalog: DotaCatalogRepository
) -> tuple[str | None, bool | None]:
    if not isinstance(item, dict) or (item_id := _positive_int(item.get("item_id"))) is None:
        return None, None
    try:
        catalog_item = catalog.get_item(item_id)
    except CatalogLookupError:
        return None, None
    return catalog_item.internal_name, not bool(catalog_item.upgrade_item_ids)


def _normalize_inventory(
    player: dict[str, Any], catalog: DotaCatalogRepository
) -> dict[str, Any]:
    return {
        "main": [
            _item_reference(player.get(f"item_{index}"), catalog) for index in range(6)
        ],
        "backpack": [
            _item_reference(player.get(f"backpack_{index}"), catalog) for index in range(3)
        ],
        "neutral": {
            "item": _item_reference(player.get("item_neutral"), catalog),
            "enhancement": _item_reference(
                player.get("item_neutral2", player.get("item_neutral_enhancement")),
                catalog,
            ),
        },
        "neutral_history": _normalize_neutral_history(
            player.get("neutral_item_history"), catalog
        ),
    }


def _normalize_neutral_history(
    history: Any, catalog: DotaCatalogRepository
) -> list[dict[str, Any]]:
    if not isinstance(history, list):
        return []
    normalized: list[dict[str, Any]] = []
    for row in history:
        if not isinstance(row, dict):
            continue
        normalized.append(
            {
                "time_seconds": row.get("time", row.get("time_seconds")),
                "item": _item_reference(
                    row.get("item_neutral", row.get("item")), catalog
                ),
                "enhancement": _item_reference(
                    row.get(
                        "item_neutral2",
                        row.get("item_neutral_enhancement", row.get("enhancement")),
                    ),
                    catalog,
                ),
            }
        )
    return normalized


def _normalize_ability_upgrades(
    upgrades: Any, catalog: DotaCatalogRepository
) -> list[dict[str, Any]]:
    if not isinstance(upgrades, list):
        return []
    sequence: list[dict[str, Any]] = []
    for upgrade_index, raw in enumerate(upgrades, start=1):
        ability_id = raw.get("ability_id", raw.get("id")) if isinstance(raw, dict) else raw
        raw_internal_name = raw.get("internal_name") if isinstance(raw, dict) else None
        sequence.append(
            _ability_reference(
                ability_id,
                catalog,
                upgrade_index=upgrade_index,
                raw_internal_name=raw_internal_name,
            )
        )
    return sequence


def _normalize_talent_selections(
    upgrades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    talent_rows = [row for row in upgrades if row["kind"] == "talent"]
    return [
        {
            "level_taken": _TALENT_PLAYER_LEVELS[index],
            "upgrade_index": row["upgrade_index"],
            "ability_id": row["ability_id"],
            "internal_name": row["internal_name"],
            "name_en": row["name_en"],
            "name_zh": row["name_zh"],
            "ability_image_path": row["ability_image_path"],
            "catalog_status": row["catalog_status"],
        }
        for index, row in enumerate(talent_rows)
        if index < len(_TALENT_PLAYER_LEVELS)
    ]


def _ability_reference(
    ability_id: Any,
    catalog: DotaCatalogRepository,
    *,
    upgrade_index: int,
    raw_internal_name: str | None = None,
) -> dict[str, Any]:
    identifier = _positive_int(ability_id)
    ability = None
    if identifier is not None:
        try:
            ability = catalog.get_ability(identifier)
        except CatalogLookupError:
            pass
    is_attribute_bonus = ability is None and identifier == _ATTRIBUTE_BONUS_ABILITY_ID
    internal_name = (
        ability.internal_name
        if ability is not None
        else _ATTRIBUTE_BONUS_INTERNAL_NAME
        if is_attribute_bonus
        else raw_internal_name
    )
    kind = "ability"
    if internal_name == "special_bonus_attributes":
        kind = "attribute_bonus"
    elif internal_name is not None and internal_name.startswith("special_bonus_"):
        kind = "talent"
    if ability is not None:
        name_en = ability.name_en
        name_zh = ability.name_zh
    elif is_attribute_bonus:
        name_en = _ATTRIBUTE_BONUS_NAME_EN
        name_zh = _ATTRIBUTE_BONUS_NAME_ZH
    else:
        name_en = None
        name_zh = None
    return {
        "upgrade_index": upgrade_index,
        "ability_id": identifier,
        "internal_name": internal_name,
        "name_en": name_en,
        "name_zh": name_zh,
        "ability_image_path": (
            f"/api/v1/assets/dota/abilities/{ability.ability_id}.png"
            if (
                ability is not None
                and not ability.is_item
                and not ability.is_talent
                and not ability.is_innate
            )
            else None
        ),
        "kind": kind,
        "catalog_status": (
            "resolved" if ability is not None else "mapped" if is_attribute_bonus else "not_found"
        ),
    }


def _item_reference(value: Any, catalog: DotaCatalogRepository) -> dict[str, Any] | None:
    if value is None or value == "" or value == 0 or value == "0":
        return None
    if (identifier := _positive_int(value)) is not None:
        detail = _item_catalog_field(identifier, catalog)
        if detail is None:
            return None
        try:
            item = catalog.get_item(identifier)
        except CatalogLookupError:
            return {"item_key": None, **detail}
        return {"item_key": item.internal_name, **detail}
    raw_key = str(value)
    try:
        item = catalog.get_item_by_internal_name(raw_key)
    except CatalogLookupError:
        return {
            "item_key": raw_key,
            "item_id": None,
            "item_name_en": None,
            "item_name_zh": None,
            "item_catalog_status": "not_found",
            "item_image_path": None,
        }
    return {
        "item_key": raw_key,
        "item_id": item.item_id,
        "item_name_en": item.name_en,
        "item_name_zh": item.name_zh,
        "item_catalog_status": "resolved",
        "item_image_path": f"/api/v1/assets/dota/items/{item.item_id}.png",
    }


def _hero_catalog_fields(hero_id: Any, catalog: DotaCatalogRepository) -> dict[str, Any]:
    identifier = _positive_int(hero_id)
    if identifier is None:
        return {
            "hero_name_en": None,
            "hero_name_zh": None,
            "hero_catalog_status": "absent",
            "hero_image_path": None,
        }
    try:
        hero = catalog.get_hero(identifier)
    except CatalogLookupError:
        return {
            "hero_name_en": None,
            "hero_name_zh": None,
            "hero_catalog_status": "not_found",
            "hero_image_path": None,
        }
    return {
        "hero_name_en": hero.name_en,
        "hero_name_zh": hero.name_zh,
        "hero_catalog_status": "resolved",
        "hero_image_path": f"/api/v1/assets/dota/heroes/{hero.hero_id}.png",
    }


def _item_catalog_details(
    items: dict[str, Any], catalog: DotaCatalogRepository
) -> dict[str, dict[str, Any]]:
    return {
        slot: detail
        for slot, value in items.items()
        if (detail := _item_catalog_field(value, catalog)) is not None
    }


def _item_catalog_field(
    item_id: Any, catalog: DotaCatalogRepository
) -> dict[str, Any] | None:
    identifier = _positive_int(item_id)
    if identifier is None:
        return None
    try:
        item = catalog.get_item(identifier)
    except CatalogLookupError:
        return {
            "item_id": identifier,
            "item_name_en": None,
            "item_name_zh": None,
            "item_catalog_status": "not_found",
            "item_image_path": None,
        }
    return {
        "item_id": identifier,
        "item_name_en": item.name_en,
        "item_name_zh": item.name_zh,
        "item_catalog_status": "resolved",
        "item_image_path": f"/api/v1/assets/dota/items/{item.item_id}.png",
    }


def _positive_int(value: Any) -> int | None:
    try:
        identifier = int(value)
    except (TypeError, ValueError):
        return None
    return identifier if identifier > 0 else None
