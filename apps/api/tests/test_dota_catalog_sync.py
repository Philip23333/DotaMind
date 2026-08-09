from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import pytest

from app.integrations.valve.catalog import (
    AbilityCatalogRecord,
    CatalogBundle,
    CatalogManifest,
    CatalogValidationError,
    HeroCatalogRecord,
    ItemCatalogRecord,
    collect_talent_bonuses,
    normalize_ability,
    normalize_hero,
    normalize_item,
    validate_catalog,
)
from app.integrations.valve.datafeed import ValveDatafeedClient
from scripts import sync_game_data


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _response(payload: object) -> _Response:
    return _Response(json.dumps(payload).encode())


def test_datafeed_transport_allowlists_endpoint_and_retries() -> None:
    requests: list[str] = []
    attempts = 0

    def opener(request, *, timeout):
        nonlocal attempts
        attempts += 1
        requests.append(request.full_url)
        if attempts == 1:
            raise OSError("transient")
        assert timeout == 3
        return _response({"result": {"data": {"heroes": []}}})

    client = ValveDatafeedClient(
        timeout_seconds=3,
        max_attempts=2,
        retry_delays_seconds=(0,),
        opener=opener,
        sleep_fn=lambda _delay: None,
    )
    assert client.herolist("schinese")["result"]["data"]["heroes"] == []
    assert attempts == 2
    assert requests[0] == requests[1]
    assert "https://www.dota2.com/datafeed/herolist?language=schinese" == requests[0]

    with pytest.raises(ValueError, match="unsupported"):
        client.fetch("https://example.test/not-datafeed")
    with pytest.raises(ValueError, match="language"):
        client.herolist("french")


def _hero_fixture() -> tuple[dict, dict]:
    talents_en = []
    for index in range(101, 109):
        talents_en.append(
            {
                "id": index,
                "name": f"special_bonus_{index}",
                "name_loc": "+{s:bonus_damage} Talent" if index == 101 else "+Talent",
                "special_values": (
                    [] if index == 101 else [{"name": "value", "values_float": [index]}]
                ),
            }
        )
    talents_zh = [
        dict(
            item,
            name_loc="+{s:bonus_damage} 天赋" if item["id"] == 101 else "+天赋",
        )
        for item in talents_en
    ]
    ability_en = {
        "id": 10,
        "name": "test_ability",
        "name_loc": "Test Ability",
        "desc_loc": "Deals %damage_bonus%%% damage.<br><b>Test</b>",
        "lore_loc": "An &amp; old spell.",
        "notes_loc": ["No HTML"],
        "scepter_loc": "Scepter: +{s:damage_bonus}",
        "shard_loc": "",
        "behavior": "24",
        "max_level": 2,
        "cooldowns": [10, 8],
        "special_values": [
            {
                "name": "damage_bonus",
                "values_float": [10, 20],
                "bonuses": [],
            },
            {
                "name": "damage",
                "values_float": [0],
                "bonuses": [{"name": "special_bonus_101", "value": 5, "operation": 0}],
            }
        ],
        "ability_is_innate": True,
        "ability_has_scepter": True,
    }
    ability_zh = dict(
        ability_en,
        name_loc="测试技能",
        desc_loc="造成 %damage_bonus%%% 点伤害。",
        lore_loc="一个古老的技能。",
        scepter_loc="神杖：+{s:damage_bonus}",
        special_values=[
            {
                "name": "damage_bonus",
                "values_float": [10, 20],
                "heading_loc": "伤害",
                "bonuses": [],
            },
            {
                "name": "damage",
                "values_float": [0],
                "heading_loc": "伤害",
                "bonuses": [{"name": "special_bonus_101", "value": 5, "operation": 0}],
            }
        ],
    )
    hero_en = {
        "id": 1,
        "name": "npc_dota_hero_test",
        "name_loc": "Test Hero",
        "str_base": 20,
        "str_gain": 2,
        "abilities": [ability_en],
        "talents": talents_en,
    }
    hero_zh = dict(hero_en, name_loc="测试英雄", abilities=[ability_zh], talents=talents_zh)
    return hero_en, hero_zh


def _catalog_fixture() -> CatalogBundle:
    hero_en, hero_zh = _hero_fixture()
    hero = normalize_hero(hero_en, hero_zh, aliases=["测试"])
    ability_records_en = [hero_en["abilities"][0], *hero_en["talents"]]
    ability_records_zh = [hero_zh["abilities"][0], *hero_zh["talents"]]
    zh_by_id = {item["id"]: item for item in ability_records_zh}
    bonus_index = collect_talent_bonuses(ability_records_en)
    abilities = [
        normalize_ability(
            item,
            zh_by_id[item["id"]],
            hero_ids=[1],
            is_talent=item["id"] != 10,
            talent_bonuses=bonus_index,
        )
        for item in ability_records_en
    ]
    detail = {
        "id": 3,
        "name": "item_test",
        "name_loc": "Test Item",
        "desc_loc": "<h1>Active</h1> +%damage_bonus%%% damage",
        "lore_loc": "Lore",
        "notes_loc": [],
        "special_values": [{"name": "damage_bonus", "values_float": [8]}],
        "item_cost": 100,
    }
    detail_zh = dict(detail, name_loc="测试物品", desc_loc="<h1>主动</h1> +%damage_bonus%%% 伤害")
    item = normalize_item(detail, detail_zh, recipe_component_ids=[1], is_recipe=False)
    component = ItemCatalogRecord(item_id=1, internal_name="item_component", name_en="Component")
    recipe = ItemCatalogRecord(
        item_id=2,
        internal_name="item_recipe_test",
        name_en="Test Item Recipe",
        is_recipe=True,
        upgrade_item_ids=[3],
    )
    manifest = CatalogManifest(
        patch="7.41e",
        generated_at=datetime.now(timezone.utc),
        locales=["english", "schinese"],
        sources=["https://www.dota2.com/datafeed"],
        entity_counts={"heroes": 1, "abilities": len(abilities), "items": 3},
    )
    bundle = CatalogBundle(
        manifest=manifest, heroes=[hero], abilities=abilities, items=[component, recipe, item]
    )
    validate_catalog(bundle.manifest, bundle.heroes, bundle.abilities, bundle.items)
    return bundle


def test_catalog_normalizes_bilingual_text_talent_bonus_and_talent_tree() -> None:
    bundle = _catalog_fixture()
    hero = bundle.heroes[0]
    assert [tier.level for tier in hero.talent_tiers] == [10, 15, 20, 25]
    ability = next(item for item in bundle.abilities if item.ability_id == 10)
    assert ability.description_en == "Deals 10 / 20% damage.\nTest"
    assert ability.description_zh == "造成 10 / 20% 点伤害。"
    assert ability.scepter_en == "Scepter: +10 / 20"
    talent = next(item for item in bundle.abilities if item.ability_id == 101)
    assert talent.name_en == "+5 Talent"
    assert (
        next(item for item in bundle.items if item.item_id == 3).description_en
        == "Active\n+8% damage"
    )
    assert all("%damage" not in field for field in (ability.description_en, ability.description_zh))


def test_catalog_rejects_unresolved_token_and_bilingual_identity_mismatch() -> None:
    hero_en, hero_zh = _hero_fixture()
    with pytest.raises(CatalogValidationError, match="identity mismatch"):
        normalize_hero(hero_en, dict(hero_zh, name="npc_dota_hero_other"))

    with pytest.raises(CatalogValidationError, match="unresolved"):
        normalize_item(
            {"id": 3, "name": "item_bad", "desc_loc": "%missing%", "special_values": []},
            {"id": 3, "name": "item_bad", "desc_loc": "%missing%", "special_values": []},
        )


def test_snapshot_writer_roundtrips_manifest_and_three_catalog_files(tmp_path, monkeypatch) -> None:
    bundle = _catalog_fixture()
    output = tmp_path / "catalog"
    monkeypatch.setattr(sync_game_data, "CATALOG_OUTPUT_DIR", output)
    sync_game_data._write_catalog_snapshot(bundle)

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    heroes = json.loads((output / "dota2_heroes.json").read_text(encoding="utf-8"))
    abilities = json.loads((output / "dota2_abilities.json").read_text(encoding="utf-8"))
    items = json.loads((output / "dota2_items.json").read_text(encoding="utf-8"))
    CatalogManifest.model_validate(manifest)
    for item in heroes:
        HeroCatalogRecord.model_validate(item)
    for item in abilities:
        AbilityCatalogRecord.model_validate(item)
    for item in items["items"]:
        ItemCatalogRecord.model_validate(item)
    assert len(heroes) == manifest["entity_counts"]["heroes"]
    assert len(abilities) == manifest["entity_counts"]["abilities"]
    assert len(items["items"]) == manifest["entity_counts"]["items"]
    assert {"manifest.json", "dota2_heroes.json", "dota2_abilities.json", "dota2_items.json"} == {
        item.name for item in output.iterdir()
    }
