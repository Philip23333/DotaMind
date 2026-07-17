"""Regenerate committed local Dota hero constants and patch records.

The runtime intentionally reads local, reviewed snapshots. This script is an
offline maintenance command: it downloads Valve's public Dota 2 datafeed,
normalizes it into the repository contracts, and writes files for review and
commit. It is never called from the request path.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yaml

API_ROOT = Path(__file__).resolve().parents[1]
ALIASES_PATH = Path(__file__).with_name("hero_aliases_zh.yaml")
HERO_OUTPUT = API_ROOT / "app" / "data" / "heroes" / "dota2_heroes.yaml"
PATCH_OUTPUT_DIR = API_ROOT / "app" / "data" / "patches"
DATAFEED_ROOT = "https://www.dota2.com/datafeed"
USER_AGENT = "DotaMind offline data sync/1.0"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--patch",
        default="latest",
        help="Patch version to sync, or 'latest' (default).",
    )
    args = parser.parse_args()

    patch = _latest_patch() if args.patch == "latest" else args.patch
    heroes = _build_hero_constants()
    patch_records = _build_patch_records(patch)

    HERO_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PATCH_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    HERO_OUTPUT.write_text(
        yaml.safe_dump(heroes, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    patch_path = PATCH_OUTPUT_DIR / f"{patch.replace('.', '_')}.json"
    patch_path.write_text(
        json.dumps(patch_records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"wrote {HERO_OUTPUT} ({len(heroes['heroes'])} heroes)")
    print(f"wrote {patch_path} ({len(patch_records['changes'])} changes)")


def _fetch(endpoint: str, **params: str) -> dict[str, Any]:
    query = urlencode(params)
    url = f"{DATAFEED_ROOT}/{endpoint}"
    if query:
        url = f"{url}?{query}"
    request = Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310 - fixed HTTPS host
                return json.load(response)
        except (OSError, URLError):
            if attempt == 2:
                raise
            sleep(1 + attempt)
    raise AssertionError("unreachable")


def _latest_patch() -> str:
    payload = _fetch("patchnoteslist", language="english")
    patches = payload.get("patches", [])
    if not patches:
        raise ValueError("Valve patchnoteslist returned no patches")
    latest = max(patches, key=lambda item: int(item["patch_timestamp"]))
    return str(latest["patch_number"])


def _build_hero_constants() -> dict[str, Any]:
    english_url = f"{DATAFEED_ROOT}/herolist?language=english"
    chinese_url = f"{DATAFEED_ROOT}/herolist?language=schinese"
    english = _result_data(_fetch("herolist", language="english"), "heroes")
    chinese = _result_data(_fetch("herolist", language="schinese"), "heroes")
    chinese_by_id = {int(hero["id"]): str(hero["name_loc"]) for hero in chinese}

    alias_payload = yaml.safe_load(ALIASES_PATH.read_text(encoding="utf-8"))
    aliases_by_id = {
        int(hero_id): [str(alias) for alias in aliases]
        for hero_id, aliases in alias_payload.get("aliases", {}).items()
    }

    heroes = []
    for hero in sorted(english, key=lambda item: int(item["id"])):
        hero_id = int(hero["id"])
        aliases = _unique([chinese_by_id.get(hero_id, ""), *aliases_by_id.get(hero_id, [])])
        heroes.append(
            {
                "id": hero_id,
                "name": str(hero["name"]),
                "localized_name": str(hero["name_loc"]),
                "aliases": aliases,
            }
        )

    return {
        "schema_version": 1,
        "sources": [english_url, chinese_url],
        "aliases_source": "apps/api/scripts/hero_aliases_zh.yaml",
        "heroes": heroes,
    }


def _build_patch_records(patch: str) -> dict[str, Any]:
    payload = _fetch("patchnotes", version=patch, language="english")
    actual_patch = str(payload.get("patch_number") or "")
    if actual_patch != patch:
        raise ValueError(f"requested patch {patch!r}, Valve returned {actual_patch!r}")

    heroes = _result_data(_fetch("herolist", language="english"), "heroes")
    items = _result_data(_fetch("itemlist", language="english"), "itemabilities")
    abilities = _result_data(_fetch("abilitylist", language="english"), "itemabilities")
    hero_by_id = {int(item["id"]): item for item in heroes}
    item_by_id = {int(item["id"]): item for item in items}
    ability_by_id = {int(item["id"]): item for item in abilities}

    changes: list[dict[str, Any]] = []
    _append_general_changes(changes, payload.get("general_notes", []))
    _append_item_changes(changes, payload.get("items", []), item_by_id, "item")
    _append_neutral_changes(changes, payload.get("neutral_items", []), ability_by_id)
    _append_hero_changes(changes, payload.get("heroes", []), hero_by_id, ability_by_id)

    timestamp = int(payload["patch_timestamp"])
    released_at = (
        datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    )
    return {
        "schema_version": 1,
        "patch": actual_patch,
        "released_at": released_at,
        "source_url": f"https://www.dota2.com/patches/{actual_patch}?l=english",
        "source_data_url": (f"{DATAFEED_ROOT}/patchnotes?version={actual_patch}&language=english"),
        "normalization": (
            "Valve datafeed flattened locally; polarity is conservative rule-based "
            "classification and neutral when direction is unclear."
        ),
        "changes": changes,
    }


def _append_general_changes(output: list[dict[str, Any]], sections: list[dict[str, Any]]) -> None:
    for section in sections:
        field = _slug(section.get("title") or "general")
        for note in section.get("generic", []):
            _append_change(output, "general", "general", field, note.get("note"))


def _append_item_changes(
    output: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    item_by_id: dict[int, dict[str, Any]],
    target_type: str,
) -> None:
    for group in groups:
        item_id = int(group["ability_id"])
        item = item_by_id.get(item_id, {})
        internal_name = str(item.get("name") or f"item_{item_id}")
        target = internal_name.removeprefix("item_")
        display_name = str(item.get("name_loc") or group.get("title") or target)
        for note in group.get("ability_notes", []):
            _append_change(
                output,
                target_type,
                target,
                _field_from_note(note.get("note"), "item"),
                note.get("note"),
                target_display_name=display_name,
                source_id=item_id,
            )


def _append_neutral_changes(
    output: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    ability_by_id: dict[int, dict[str, Any]],
) -> None:
    target_type = "neutral_item"
    for group in groups:
        if group.get("is_general_note"):
            if str(group.get("title", "")).strip().lower() == "enchantments":
                target_type = "enchantment"
            continue
        ability_id = int(group["ability_id"])
        item = ability_by_id.get(ability_id, {})
        internal_name = str(item.get("name") or f"neutral_{ability_id}")
        target = internal_name.removeprefix("item_")
        display_name = str(item.get("name_loc") or group.get("title") or target)
        for note in group.get("ability_notes", []):
            _append_change(
                output,
                target_type,
                target,
                _field_from_note(note.get("note"), "neutral_item"),
                note.get("note"),
                target_display_name=display_name,
                source_id=ability_id,
            )


def _append_hero_changes(
    output: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    hero_by_id: dict[int, dict[str, Any]],
    ability_by_id: dict[int, dict[str, Any]],
) -> None:
    for group in groups:
        hero_id = int(group["hero_id"])
        hero = hero_by_id.get(hero_id, {})
        internal_name = str(hero.get("name") or f"npc_dota_hero_{hero_id}")
        target = internal_name.removeprefix("npc_dota_hero_")
        display_name = str(hero.get("name_loc") or target)

        for note in group.get("hero_notes", []):
            _append_change(
                output,
                "hero",
                target,
                _field_from_note(note.get("note"), note.get("icon") or "base_stats"),
                note.get("note"),
                target_display_name=display_name,
                source_id=hero_id,
            )
        for note in group.get("talent_notes", []):
            _append_change(
                output,
                "hero",
                target,
                "talent",
                note.get("note"),
                target_display_name=display_name,
                source_id=hero_id,
            )
        for ability_group in group.get("abilities", []):
            ability_id = int(ability_group["ability_id"])
            ability = ability_by_id.get(ability_id, {})
            field = str(ability.get("name") or f"ability_{ability_id}")
            ability_name = str(ability.get("name_loc") or field)
            for note in ability_group.get("ability_notes", []):
                _append_change(
                    output,
                    "hero",
                    target,
                    field,
                    note.get("note"),
                    target_display_name=display_name,
                    field_display_name=ability_name,
                    source_id=hero_id,
                    ability_id=ability_id,
                )


def _append_change(
    output: list[dict[str, Any]],
    target_type: str,
    target: str,
    field: str,
    raw: Any,
    **extra: Any,
) -> None:
    cleaned = _clean_note(raw)
    if not cleaned:
        return
    record = {
        "target_type": target_type,
        "target": target,
        "field": field,
        "polarity": _polarity(cleaned),
        "raw": cleaned,
    }
    record.update({key: value for key, value in extra.items() if value not in (None, "")})
    output.append(record)


def _polarity(note: str) -> str:
    lowered = note.lower()
    beneficial = (
        "damage",
        "range",
        "radius",
        "aoe",
        "health",
        "mana regen",
        "health regen",
        "armor",
        "evasion",
        "lifesteal",
        "attack speed",
        "move speed",
        "movement speed",
        "slow resistance",
        "stun duration",
        "max charges",
        "bonus",
    )
    burdens = (
        "cooldown",
        "mana cost",
        "recipe cost",
        "total cost",
        "damage taken",
        "incoming damage",
        "penalty",
        "delay",
    )
    if "increased" in lowered:
        if any(term in lowered for term in burdens):
            return "nerf"
        if any(term in lowered for term in beneficial):
            return "buff"
    if "decreased" in lowered or "reduced" in lowered:
        if any(term in lowered for term in burdens):
            return "buff"
        if any(term in lowered for term in beneficial):
            return "nerf"
    return "neutral"


def _field_from_note(note: Any, fallback: Any) -> str:
    cleaned = _clean_note(note)
    prefix = re.split(
        r"\s+(?:increased|decreased|reduced|rescaled|changed|now|no longer)\b",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    if 0 < len(prefix) <= 80:
        return _slug(prefix)
    return _slug(fallback)


def _clean_note(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _slug(value: Any) -> str:
    text = _clean_note(value).lower().replace("'", "")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "unknown"


def _unique(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        cleaned = value.strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _result_data(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    data = payload.get("result", {}).get("data", {}).get(key)
    if not isinstance(data, list):
        raise ValueError(f"Valve datafeed response missing result.data.{key}")
    return data


if __name__ == "__main__":
    main()
