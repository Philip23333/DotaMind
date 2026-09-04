from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.integrations.valve.catalog import (
    AbilityCatalogRecord,
    CatalogBundle,
    CatalogManifest,
    HeroCatalogRecord,
    ItemCatalogRecord,
    RecipeEdge,
    SpecialValue,
    TalentTier,
)
from app.integrations.valve.catalog_repository import (
    CatalogLookupError,
    CatalogSnapshotError,
    DotaCatalogRepository,
)


def _bundle() -> CatalogBundle:
    abilities = [
        AbilityCatalogRecord(
            ability_id=10,
            internal_name="test_ability",
            name_en="Test Ability",
            name_zh="测试技能",
            description_en="Deals 10 damage.",
            description_zh="造成 10 点伤害。",
            hero_ids=[1],
        )
    ]
    for index in range(101, 109):
        abilities.append(
            AbilityCatalogRecord(
                ability_id=index,
                internal_name=f"special_bonus_{index}",
                name_en=f"+{index} Talent",
                name_zh=f"+{index} 天赋",
                is_talent=True,
                hero_ids=[1],
                special_values=[SpecialValue(name="value", values=[index])],
            )
        )
    heroes = [
        HeroCatalogRecord(
            hero_id=1,
            internal_name="npc_dota_hero_test",
            name_en="Test Hero",
            name_zh="测试英雄",
            aliases=["测试"],
            ability_ids=[10],
            talent_tiers=[
                TalentTier(level=10, left_ability_id=101, right_ability_id=102),
                TalentTier(level=15, left_ability_id=103, right_ability_id=104),
                TalentTier(level=20, left_ability_id=105, right_ability_id=106),
                TalentTier(level=25, left_ability_id=107, right_ability_id=108),
            ],
        )
    ]
    items = [
        ItemCatalogRecord(
            item_id=1,
            internal_name="item_component",
            name_en="Component",
            price=80,
        ),
        ItemCatalogRecord(
            item_id=2,
            internal_name="item_recipe_test_item",
            name_en="Test Item Recipe",
            name_zh="测试物品图纸",
            price=20,
            is_recipe=True,
            upgrade_item_ids=[3],
        ),
        ItemCatalogRecord(
            item_id=3,
            internal_name="item_test_item",
            name_en="Test Item",
            name_zh="测试物品",
            recipe_component_ids=[1],
            price=100,
        ),
    ]
    manifest = CatalogManifest(
        patch="7.41e",
        generated_at=datetime.now(timezone.utc),
        locales=["english", "schinese"],
        sources=["https://www.dota2.com/datafeed"],
        entity_counts={"heroes": 1, "abilities": 9, "items": 3},
    )
    return CatalogBundle(
        manifest=manifest,
        heroes=heroes,
        abilities=abilities,
        items=items,
        recipes=[
            RecipeEdge(recipe_item_id=2, component_item_ids=[1], upgrade_item_ids=[3])
        ],
    )


def _write_bundle(directory, bundle: CatalogBundle) -> None:
    directory.mkdir(exist_ok=True)
    (directory / "manifest.json").write_text(
        json.dumps(bundle.manifest.model_dump(mode="json")), encoding="utf-8"
    )
    (directory / "dota2_heroes.json").write_text(
        json.dumps([item.model_dump(mode="json") for item in bundle.heroes]), encoding="utf-8"
    )
    (directory / "dota2_abilities.json").write_text(
        json.dumps([item.model_dump(mode="json") for item in bundle.abilities]), encoding="utf-8"
    )
    (directory / "dota2_items.json").write_text(
        json.dumps(
            {
                "items": [item.model_dump(mode="json") for item in bundle.items],
                "recipes": [item.model_dump(mode="json") for item in bundle.recipes],
            }
        ),
        encoding="utf-8",
    )


def test_repository_loads_once_and_returns_deep_copies(tmp_path) -> None:
    _write_bundle(tmp_path, _bundle())
    repository = DotaCatalogRepository(tmp_path)

    hero = repository.get_hero(1)
    hero.aliases.append("mutated")
    assert "mutated" not in repository.get_hero(1).aliases
    assert repository.get_hero_abilities(1)[0].ability_id == 10
    assert [tier.level for tier in repository.get_hero_talent_tree(1)] == [10, 15, 20, 25]
    assert repository.hero_name_index() == {1: "Test Hero"}
    ability_index = repository.ability_name_index()
    ability_id = next(iter(ability_index))
    assert ability_index[ability_id] == repository.get_ability(ability_id).name_en
    item_index = repository.item_key_index()
    item_record = next(
        record for record in repository.list_items() if record.internal_name.startswith("item_")
    )
    assert item_index[item_record.internal_name] == item_record.item_id
    assert item_index[item_record.internal_name.removeprefix("item_")] == item_record.item_id
    assert repository.snapshot_metadata()["status"] == "committed_snapshot"

    with pytest.raises(CatalogLookupError, match="item not found"):
        repository.get_item(999)


def test_repository_recipe_edges_cover_finished_and_recipe_items_with_deep_copies(
    tmp_path,
) -> None:
    _write_bundle(tmp_path, _bundle())
    repository = DotaCatalogRepository(tmp_path)

    finished_edges = repository.get_item_recipe_edges(3)
    recipe_edges = repository.get_item_recipe_edges(2)

    assert finished_edges == recipe_edges
    assert finished_edges[0].recipe_item_id == 2
    assert finished_edges[0].component_item_ids == [1]
    finished_edges[0].component_item_ids.append(999)
    assert repository.get_item_recipe_edges(3)[0].component_item_ids == [1]
    with pytest.raises(CatalogLookupError, match="item not found"):
        repository.get_item_recipe_edges(999)


def test_repository_resolvers_support_exact_fuzzy_and_recipe_scope(tmp_path) -> None:
    _write_bundle(tmp_path, _bundle())
    repository = DotaCatalogRepository(tmp_path)

    assert repository.find_hero("测试")["hero"]["hero_id"] == 1
    assert repository.find_hero("test her")["status"] == "resolved"
    assert repository.find_hero("unknown")["status"] == "not_found"
    assert repository.resolve_item("测试物品")["item"]["item_id"] == 3
    assert repository.resolve_item("测试物品图纸")["item"]["item_id"] == 2


def test_repository_fails_fast_for_missing_or_inconsistent_snapshot(tmp_path) -> None:
    with pytest.raises(CatalogSnapshotError, match="missing"):
        DotaCatalogRepository(tmp_path)
    bundle = _bundle()
    bundle.manifest.entity_counts["items"] = 2
    _write_bundle(tmp_path, bundle)
    with pytest.raises(CatalogSnapshotError, match="invalid Dota catalog snapshot"):
        DotaCatalogRepository(tmp_path)
