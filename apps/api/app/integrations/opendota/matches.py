"""OpenDota match detail access and deterministic normalization."""

from __future__ import annotations

from typing import Any

from app.integrations.opendota.transport import OpenDotaTransport
from app.integrations.valve.catalog_repository import (
    CatalogLookupError,
    DotaCatalogRepository,
    load_default_catalog_repository,
)


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
    return {
        "player_slot": player.get("player_slot"),
        "account_id": player.get("account_id"),
        "name": player.get("name", player.get("personaname")),
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
    }


def _hero_catalog_fields(hero_id: Any, catalog: DotaCatalogRepository) -> dict[str, Any]:
    identifier = _positive_int(hero_id)
    if identifier is None:
        return {"hero_name_en": None, "hero_name_zh": None, "hero_catalog_status": "absent"}
    try:
        hero = catalog.get_hero(identifier)
    except CatalogLookupError:
        return {
            "hero_name_en": None,
            "hero_name_zh": None,
            "hero_catalog_status": "not_found",
        }
    return {
        "hero_name_en": hero.name_en,
        "hero_name_zh": hero.name_zh,
        "hero_catalog_status": "resolved",
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
        }
    return {
        "item_id": identifier,
        "item_name_en": item.name_en,
        "item_name_zh": item.name_zh,
        "item_catalog_status": "resolved",
    }


def _positive_int(value: Any) -> int | None:
    try:
        identifier = int(value)
    except (TypeError, ValueError):
        return None
    return identifier if identifier > 0 else None
