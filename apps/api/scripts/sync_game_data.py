"""Regenerate committed local Dota catalog and patch records.

The runtime intentionally reads local, reviewed snapshots. This script is an
offline maintenance command: it downloads Valve's public Dota 2 datafeed,
normalizes it into the repository contracts, and writes files for review and
commit. It is never called from the request path.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.integrations.valve.catalog import (  # noqa: E402
    CatalogBundle,
    CatalogExcludedEntity,
    CatalogManifest,
    CatalogSyncAudit,
    CatalogValidationError,
    RecipeEdge,
    extract_display_tokens,
    index_talent_bonus_candidates,
    normalize_ability,
    normalize_hero,
    normalize_item,
    resolve_talent_bonus_requirements,
    validate_catalog,
    validate_sync_audit,
)
from app.integrations.valve.datafeed import DATAFEED_ROOT, ValveDatafeedClient  # noqa: E402

ALIASES_PATH = Path(__file__).with_name("hero_aliases_zh.yaml")
PATCH_OUTPUT_DIR = API_ROOT / "app" / "data" / "patches"
CATALOG_OUTPUT_DIR = API_ROOT / "app" / "data" / "catalog"
CATALOG_MANIFEST_OUTPUT = CATALOG_OUTPUT_DIR / "manifest.json"
CATALOG_HERO_OUTPUT = CATALOG_OUTPUT_DIR / "dota2_heroes.json"
CATALOG_ABILITY_OUTPUT = CATALOG_OUTPUT_DIR / "dota2_abilities.json"
CATALOG_ITEM_OUTPUT = CATALOG_OUTPUT_DIR / "dota2_items.json"
CATALOG_AUDIT_OUTPUT = CATALOG_OUTPUT_DIR / "sync_audit.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--patch",
        default="latest",
        help="Patch version to sync, or 'latest' (default).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Concurrent detail requests for the offline sync (default: 8).",
    )
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 16:
        parser.error("--workers must be between 1 and 16")

    client = ValveDatafeedClient()
    patch = _latest_patch(client) if args.patch == "latest" else args.patch
    bundle = _build_catalog_snapshot(client, patch, workers=args.workers)
    _write_catalog_snapshot(bundle)
    patch_records = _build_patch_records(client, patch)

    PATCH_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    patch_path = PATCH_OUTPUT_DIR / f"{patch.replace('.', '_')}.json"
    patch_path.write_text(
        json.dumps(patch_records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"wrote {patch_path} ({len(patch_records['changes'])} changes)")
    print(
        f"wrote {CATALOG_OUTPUT_DIR} "
        f"({len(bundle.heroes)} heroes, {len(bundle.abilities)} abilities, "
        f"{len(bundle.items)} items)"
    )


def _latest_patch(client: ValveDatafeedClient) -> str:
    payload = client.patchnoteslist("english")
    patches = payload.get("patches", [])
    if not patches:
        raise ValueError("Valve patchnoteslist returned no patches")
    latest = max(patches, key=lambda item: int(item["patch_timestamp"]))
    return str(latest["patch_number"])


def _build_patch_records(client: ValveDatafeedClient, patch: str) -> dict[str, Any]:
    payload = client.patchnotes(patch, "english")
    actual_patch = str(payload.get("patch_number") or "")
    if actual_patch != patch:
        raise ValueError(f"requested patch {patch!r}, Valve returned {actual_patch!r}")

    heroes = _result_data(client.herolist("english"), "heroes")
    items = _result_data(client.itemlist("english"), "itemabilities")
    abilities = _result_data(client.abilitylist("english"), "itemabilities")
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


def _build_catalog_snapshot(
    client: ValveDatafeedClient,
    patch: str,
    *,
    workers: int = 8,
    generated_at: datetime | None = None,
) -> CatalogBundle:
    """Fetch and normalize the complete static catalog in memory.

    Hero detail responses contain the authoritative visible hero ability and
    talent records. The bilingual ability list validates their IDs/names; English
    ability details are additionally fetched only for filtered non-output
    auxiliary abilities that may carry otherwise hidden talent bonus edges.
    Item details are fetched for every item-list ID because item-list records do
    not contain descriptions or special values.
    """

    hero_en = _result_data(client.herolist("english"), "heroes")
    hero_zh = _result_data(client.herolist("schinese"), "heroes")
    _validate_summary_identity(hero_en, hero_zh, "hero")
    hero_ids = [int(hero["id"]) for hero in hero_en]
    hero_details_en = _parallel_details(
        hero_ids,
        lambda hero_id: _result_data(client.herodata(hero_id, "english"), "heroes")[0],
        workers,
    )
    hero_details_zh = _parallel_details(
        hero_ids,
        lambda hero_id: _result_data(client.herodata(hero_id, "schinese"), "heroes")[0],
        workers,
    )

    alias_payload = yaml.safe_load(ALIASES_PATH.read_text(encoding="utf-8"))
    aliases_by_id = {
        int(hero_id): [str(alias) for alias in aliases]
        for hero_id, aliases in alias_payload.get("aliases", {}).items()
    }
    heroes = [
        normalize_hero(
            hero_details_en[hero_id],
            hero_details_zh[hero_id],
            aliases=aliases_by_id.get(hero_id, []),
        )
        for hero_id in sorted(hero_ids)
    ]

    ability_en_by_id: dict[int, dict[str, Any]] = {}
    ability_zh_by_id: dict[int, dict[str, Any]] = {}
    ability_hero_ids: dict[int, set[int]] = {}
    ability_records_en_by_hero_id: dict[int, list[dict[str, Any]]] = {}
    talent_ids: set[int] = set()
    for hero_id in sorted(hero_ids):
        details_en = hero_details_en[hero_id]
        details_zh = hero_details_zh[hero_id]
        en_records = [*(details_en.get("abilities") or []), *(details_en.get("talents") or [])]
        zh_records = [*(details_zh.get("abilities") or []), *(details_zh.get("talents") or [])]
        ability_records_en_by_hero_id[hero_id] = en_records
        zh_by_id = _join_by_id(zh_records, "ability")
        for record in en_records:
            ability_id = int(record["id"])
            counterpart = zh_by_id.get(ability_id)
            if counterpart is None:
                raise CatalogValidationError(
                    f"hero {hero_id} ability {ability_id} has no Chinese detail record"
                )
            existing = ability_en_by_id.get(ability_id)
            if existing is not None and str(existing["name"]) != str(record["name"]):
                raise CatalogValidationError(
                    f"ability {ability_id} internal name changed across heroes"
                )
            ability_en_by_id[ability_id] = record
            ability_zh_by_id[ability_id] = counterpart
            ability_hero_ids.setdefault(ability_id, set()).add(hero_id)
        talent_ids.update(int(talent["id"]) for talent in details_en.get("talents") or [])

    # Fetch both lists to verify every hero-owned ability/talent is a known
    # Datafeed entity and that the two locale lists agree on internal names.
    ability_list_en = _result_data(client.abilitylist("english"), "itemabilities")
    ability_list_zh = _result_data(client.abilitylist("schinese"), "itemabilities")
    _validate_summary_identity(ability_list_en, ability_list_zh, "ability")
    ability_summary_ids = {int(item["id"]) for item in ability_list_en}
    missing_summary_ids = sorted(set(ability_en_by_id) - ability_summary_ids)
    if missing_summary_ids:
        raise CatalogValidationError(
            f"hero details reference abilities absent from abilitylist: {missing_summary_ids[:5]}"
        )

    item_en = _result_data(client.itemlist("english"), "itemabilities")
    item_zh = _result_data(client.itemlist("schinese"), "itemabilities")
    _validate_summary_identity(item_en, item_zh, "item")
    item_ids = [int(item["id"]) for item in item_en]

    auxiliary_ids = _auxiliary_ability_ids(
        ability_list_en,
        visible_ability_ids=set(ability_en_by_id),
        talent_ids=talent_ids,
        item_ids=set(item_ids),
    )
    auxiliary_details_en = _parallel_details(
        auxiliary_ids,
        lambda ability_id: _result_data(
            client.abilitydata(ability_id, "english"), "abilities"
        )[0],
        workers,
    )
    auxiliary_bonus_index = index_talent_bonus_candidates(
        record
        for ability_id, record in sorted(auxiliary_details_en.items())
        if not record.get("is_item") and ability_id not in ability_en_by_id
    )

    talent_bonuses_by_id: dict[int, dict[str, dict[str, Any]]] = {}
    for talent_id in sorted(talent_ids):
        primary_records: list[dict[str, Any]] = []
        for hero_id in sorted(ability_hero_ids[talent_id]):
            primary_records.extend(ability_records_en_by_hero_id[hero_id])
        primary_bonus_index = index_talent_bonus_candidates(primary_records)
        talent_bonuses_by_id[talent_id] = resolve_talent_bonus_requirements(
            ability_en_by_id[talent_id],
            primary_bonus_index,
            auxiliary_bonus_index,
            localized_talents=[ability_zh_by_id[talent_id]],
        )

    abilities = [
        normalize_ability(
            ability_en_by_id[ability_id],
            ability_zh_by_id[ability_id],
            hero_ids=ability_hero_ids[ability_id],
            is_talent=ability_id in talent_ids,
            talent_bonuses=talent_bonuses_by_id.get(ability_id),
        )
        for ability_id in sorted(ability_en_by_id)
    ]

    item_details_en = _parallel_details(
        item_ids,
        lambda item_id: _result_data(client.itemdata(item_id, "english"), "items")[0],
        workers,
    )
    item_details_zh = _parallel_details(
        item_ids,
        lambda item_id: _result_data(client.itemdata(item_id, "schinese"), "items")[0],
        workers,
    )
    summary_by_id = {int(item["id"]): item for item in item_en}
    summary_zh_by_id = {int(item["id"]): item for item in item_zh}
    components_by_target, upgrades_by_recipe, recipe_edges = _recipe_relations(summary_by_id)
    excluded_entities = _reviewed_catalog_exclusions(
        summary_by_id,
        summary_zh_by_id,
        item_details_en,
        item_details_zh,
        components_by_target,
        upgrades_by_recipe,
        recipe_edges,
    )
    excluded_item_ids = {
        excluded.entity_id
        for excluded in excluded_entities
        if excluded.entity_type == "item"
    }
    items = [
        normalize_item(
            item_details_en[item_id],
            item_details_zh[item_id],
            recipe_component_ids=components_by_target.get(item_id, []),
            upgrade_item_ids=upgrades_by_recipe.get(item_id, []),
            is_recipe=bool(
                str(summary_by_id[item_id].get("name") or "").startswith("item_recipe_")
            ),
            neutral_tier=summary_by_id[item_id].get("neutral_item_tier"),
        )
        for item_id in sorted(item_ids)
        if item_id not in excluded_item_ids
    ]

    generated_at = generated_at or datetime.now(timezone.utc)
    manifest = CatalogManifest(
        patch=patch,
        generated_at=generated_at,
        locales=["english", "schinese"],
        sources=[
            f"{DATAFEED_ROOT}/herolist",
            f"{DATAFEED_ROOT}/herodata",
            f"{DATAFEED_ROOT}/abilitylist",
            f"{DATAFEED_ROOT}/abilitydata",
            f"{DATAFEED_ROOT}/itemlist",
            f"{DATAFEED_ROOT}/itemdata",
            f"{DATAFEED_ROOT}/patchnoteslist",
        ],
        entity_counts={"heroes": len(heroes), "abilities": len(abilities), "items": len(items)},
    )
    sync_audit = CatalogSyncAudit(
        patch=patch,
        generated_at=generated_at,
        excluded_entities=excluded_entities,
    )
    validate_catalog(manifest, heroes, abilities, items)
    validate_sync_audit(manifest, sync_audit, heroes, abilities, items)
    return CatalogBundle(
        manifest=manifest,
        heroes=heroes,
        abilities=abilities,
        items=items,
        recipes=recipe_edges,
        sync_audit=sync_audit,
    )


def _write_catalog_snapshot(bundle: CatalogBundle) -> None:
    """Validate again and atomically replace all five catalog files."""

    validate_catalog(bundle.manifest, bundle.heroes, bundle.abilities, bundle.items)
    if bundle.sync_audit is None:
        raise CatalogValidationError("catalog sync audit is required before snapshot writing")
    validate_sync_audit(
        bundle.manifest,
        bundle.sync_audit,
        bundle.heroes,
        bundle.abilities,
        bundle.items,
    )
    CATALOG_OUTPUT_DIR.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix=".catalog-", dir=CATALOG_OUTPUT_DIR.parent))
    payloads = {
        "manifest.json": bundle.manifest.model_dump(mode="json"),
        "dota2_heroes.json": [item.model_dump(mode="json") for item in bundle.heroes],
        "dota2_abilities.json": [item.model_dump(mode="json") for item in bundle.abilities],
        "dota2_items.json": {
            "items": [item.model_dump(mode="json") for item in bundle.items],
            "recipes": [edge.model_dump(mode="json") for edge in bundle.recipes],
        },
        "sync_audit.json": bundle.sync_audit.model_dump(mode="json"),
    }
    try:
        for filename, payload in payloads.items():
            path = temporary_dir / filename
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        for filename in payloads:
            target = CATALOG_OUTPUT_DIR / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary_dir / filename, target)
    finally:
        for child in temporary_dir.iterdir():
            child.unlink()
        temporary_dir.rmdir()


def _reviewed_catalog_exclusions(
    summaries_en: dict[int, dict[str, Any]],
    summaries_zh: dict[int, dict[str, Any]],
    details_en: dict[int, dict[str, Any]],
    details_zh: dict[int, dict[str, Any]],
    components_by_target: dict[int, set[int]],
    upgrades_by_recipe: dict[int, set[int]],
    recipe_edges: list[RecipeEdge],
) -> list[CatalogExcludedEntity]:
    item_id = 825
    internal_name = "item_ascetic_cap"
    try:
        summary_en = summaries_en[item_id]
        summary_zh = summaries_zh[item_id]
        detail_en = details_en[item_id]
        detail_zh = details_zh[item_id]
    except KeyError as exc:
        raise CatalogValidationError(
            "item 825 exclusion review required: official summary/detail channel changed"
        ) from exc

    identities = {
        (int(record.get("id") or 0), str(record.get("name") or ""))
        for record in (summary_en, summary_zh, detail_en, detail_zh)
    }
    if identities != {(item_id, internal_name)}:
        raise CatalogValidationError(
            "item 825 exclusion review required: bilingual identity drifted: "
            f"{sorted(identities)!r}"
        )

    raw_description_en = str(detail_en.get("desc_loc") or "")
    raw_description_zh = str(detail_zh.get("desc_loc") or "")
    expected_tokens = ["duration", "slow_resistance", "status_resistance"]
    tokens_en = extract_display_tokens(raw_description_en)
    tokens_zh = extract_display_tokens(raw_description_zh)
    if tokens_en != expected_tokens or tokens_zh != expected_tokens:
        raise CatalogValidationError(
            "item 825 exclusion review required: bilingual unresolved token set drifted: "
            f"english={tokens_en!r}, schinese={tokens_zh!r}"
        )

    expected_summary_status = {
        "neutral_item_tier": -1,
        "is_pregame_suggested": False,
        "is_earlygame_suggested": False,
        "is_lategame_suggested": False,
        "recipes": [],
        "is_innate": False,
    }
    for locale, summary in (("English", summary_en), ("Chinese", summary_zh)):
        actual = {key: summary.get(key) for key in expected_summary_status}
        if actual != expected_summary_status:
            raise CatalogValidationError(
                f"item 825 exclusion review required: {locale} summary status drifted: {actual!r}"
            )

    expected_detail_status = {
        "is_item": True,
        "item_cost": 0,
        "item_initial_charges": 0,
        "item_neutral_tier": 4294967295,
        "item_stock_max": 0,
        "item_stock_time": 0,
        "item_quality": 1,
    }
    for locale, detail in (("English", detail_en), ("Chinese", detail_zh)):
        actual = {key: detail.get(key) for key in expected_detail_status}
        if actual != expected_detail_status:
            raise CatalogValidationError(
                f"item 825 exclusion review required: {locale} detail status drifted: {actual!r}"
            )

    special_names_en = sorted(
        str(value.get("name") or "") for value in detail_en.get("special_values") or []
    )
    special_names_zh = sorted(
        str(value.get("name") or "") for value in detail_zh.get("special_values") or []
    )
    expected_special_names = ["AbilityCooldown"]
    if (
        special_names_en != expected_special_names
        or special_names_zh != expected_special_names
    ):
        raise CatalogValidationError(
            "item 825 exclusion review required: effect special fields changed: "
            f"english={special_names_en!r}, schinese={special_names_zh!r}"
        )

    referencing_edges = [
        edge.model_dump(mode="json")
        for edge in recipe_edges
        if item_id == edge.recipe_item_id
        or item_id in edge.component_item_ids
        or item_id in edge.upgrade_item_ids
    ]
    recipe_evidence = {
        "component_ids_if_upgrade_target": sorted(components_by_target.get(item_id, set())),
        "upgrade_ids_if_recipe": sorted(upgrades_by_recipe.get(item_id, set())),
        "referencing_edges": referencing_edges,
    }
    if any(recipe_evidence.values()):
        raise CatalogValidationError(
            f"item 825 exclusion review required: recipe graph changed: {recipe_evidence!r}"
        )

    return [
        CatalogExcludedEntity(
            entity_type="item",
            entity_id=item_id,
            internal_name=internal_name,
            reason=(
                "Official Datafeed still lists a legacy/unclassified item whose bilingual effect "
                "description references three absent effect fields and whose acquisition/recipe "
                "status is inactive."
            ),
            raw_description_en=raw_description_en,
            raw_description_zh=raw_description_zh,
            unresolved_tokens_en=tokens_en,
            unresolved_tokens_zh=tokens_zh,
            official_status_evidence={
                "summary": expected_summary_status,
                "detail": expected_detail_status,
                "special_value_names": expected_special_names,
                "recipe_graph": recipe_evidence,
                "source_endpoints": [
                    f"{DATAFEED_ROOT}/itemlist",
                    f"{DATAFEED_ROOT}/itemdata",
                ],
            },
        )
    ]


def _auxiliary_ability_ids(
    ability_summaries: list[dict[str, Any]],
    *,
    visible_ability_ids: set[int],
    talent_ids: set[int],
    item_ids: set[int],
) -> list[int]:
    """Select official non-output abilities that may carry talent bonus edges."""

    output: list[int] = []
    for summary in ability_summaries:
        ability_id = int(summary["id"])
        internal_name = str(summary.get("name") or "")
        if ability_id <= 0:
            continue
        if ability_id in visible_ability_ids or ability_id in talent_ids or ability_id in item_ids:
            continue
        # Datafeed summaries do not expose an is_talent flag. Valve's stable
        # special_bonus namespace is used only to avoid fetching talent records;
        # it is never used to associate an auxiliary ability with a hero.
        if internal_name.startswith("special_bonus_"):
            continue
        output.append(ability_id)
    return sorted(set(output))


def _parallel_details(
    identifiers: list[int], fetch: Any, workers: int
) -> dict[int, dict[str, Any]]:
    output: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch, identifier): identifier for identifier in identifiers}
        for future in as_completed(futures):
            identifier = futures[future]
            record = future.result()
            if not isinstance(record, dict):
                raise CatalogValidationError(f"Datafeed detail {identifier} is not an object")
            output[identifier] = record
    if set(output) != set(identifiers):
        raise CatalogValidationError("Datafeed detail response set is incomplete")
    return output


def _join_by_id(records: list[dict[str, Any]], entity: str) -> dict[int, dict[str, Any]]:
    output: dict[int, dict[str, Any]] = {}
    for record in records:
        identifier = int(record["id"])
        if identifier in output:
            raise CatalogValidationError(f"duplicate {entity} ID {identifier}")
        output[identifier] = record
    return output


def _validate_summary_identity(
    english: list[dict[str, Any]], chinese: list[dict[str, Any]], entity: str
) -> None:
    en_by_id = _join_by_id(english, entity)
    zh_by_id = _join_by_id(chinese, entity)
    if set(en_by_id) != set(zh_by_id):
        raise CatalogValidationError(f"{entity} English/Chinese ID sets differ")
    for identifier, record in en_by_id.items():
        if str(record.get("name")) != str(zh_by_id[identifier].get("name")):
            raise CatalogValidationError(f"{entity} {identifier} internal names differ")


def _recipe_relations(
    summaries: dict[int, dict[str, Any]],
) -> tuple[dict[int, set[int]], dict[int, set[int]], list[RecipeEdge]]:
    by_name = {str(item.get("name")): item_id for item_id, item in summaries.items()}
    components_by_target: dict[int, set[int]] = {}
    upgrades_by_recipe: dict[int, set[int]] = {}
    edges: list[RecipeEdge] = []
    for recipe_item_id, summary in summaries.items():
        recipe_name = str(summary.get("name") or "")
        if not recipe_name.startswith("item_recipe_"):
            continue
        target_name = recipe_name.replace("item_recipe_", "item_", 1)
        target_id = by_name.get(target_name)
        for recipe in summary.get("recipes") or []:
            component_ids = {int(item_id) for item_id in recipe.get("items") or []}
            if not component_ids:
                raise CatalogValidationError(f"recipe {recipe_item_id} has no components")
            if target_id is None:
                raise CatalogValidationError(f"recipe {recipe_item_id} has no upgrade target")
            components_by_target.setdefault(target_id, set()).update(component_ids)
            upgrades_by_recipe.setdefault(recipe_item_id, set()).add(target_id)
            edges.append(
                RecipeEdge(
                    recipe_item_id=recipe_item_id,
                    component_item_ids=sorted(component_ids),
                    upgrade_item_ids=[target_id],
                )
            )
    return components_by_target, upgrades_by_recipe, edges


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


def _result_data(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    data = payload.get("result", {}).get("data", {}).get(key)
    if not isinstance(data, list):
        raise ValueError(f"Valve datafeed response missing result.data.{key}")
    return data


if __name__ == "__main__":
    main()
