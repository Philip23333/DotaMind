"""Deterministic local-catalog enrichment tests for product chat presentation."""

import json
import shutil
from pathlib import Path

import pytest

from app.integrations.valve.catalog_repository import (
    CATALOG_DIR,
    load_default_catalog_repository,
)
from app.vnext.data_updates.catalog_store import CatalogSnapshotStore
from app.vnext.product import presentation
from app.vnext.product.presentation import DotaVisualEntityEnricher


@pytest.fixture(scope="module")
def enricher() -> DotaVisualEntityEnricher:
    return DotaVisualEntityEnricher()


def test_hero_aliases_resolve_to_one_local_visual_entity(
    enricher: DotaVisualEntityEnricher,
) -> None:
    entities = enricher.match("不朽尸王（Undying，尸王）发挥出色。")

    heroes = [entity for entity in entities if entity.kind == "hero"]
    assert len(heroes) == 1
    assert heroes[0].imagePath == "/api/v1/assets/dota/heroes/85.png"
    assert heroes[0].label == "不朽尸王"
    assert {"不朽尸王", "Undying", "尸王"}.issubset(heroes[0].names)


def test_normal_ability_and_team_alias_resolve_to_local_visual_entities(
    enricher: DotaVisualEntityEnricher,
) -> None:
    entities = enricher.match("Team Spirit（TS）依靠腐朽（Decay）取得优势。")

    assert {(entity.kind, entity.imagePath) for entity in entities} == {
        ("team", "/api/v1/assets/esports/teams/1669.png"),
        ("ability", "/api/v1/assets/dota/abilities/5442.png"),
    }


def test_item_aliases_resolve_to_one_local_visual_entity(
    enricher: DotaVisualEntityEnricher,
) -> None:
    entities = enricher.match("跳刀（Blink Dagger / 闪烁匕首）是核心装备。")

    items = [entity for entity in entities if entity.kind == "item"]
    assert len(items) == 1
    assert items[0].imagePath == "/api/v1/assets/dota/items/1.png"
    assert items[0].label == "闪烁匕首"
    assert {"跳刀", "Blink Dagger", "闪烁匕首"}.issubset(items[0].names)


def test_unknown_text_and_ascii_substrings_do_not_create_visual_entities(
    enricher: DotaVisualEntityEnricher,
) -> None:
    assert enricher.match("mystery teams 的战术与未知英雄无关。") == []


def test_missing_ability_image_keeps_catalog_name_lookup_but_emits_no_icon(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(presentation, "CATALOG_DIR", tmp_path)
    repository = load_default_catalog_repository()
    ability = repository.get_ability(5442)
    assert ability.name_zh == "腐朽"

    assert DotaVisualEntityEnricher().match("腐朽（Decay）") == []

    image = tmp_path / "images" / "abilities" / "5442.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    entities = DotaVisualEntityEnricher().match("腐朽（Decay）")

    assert [(entity.kind, entity.imagePath) for entity in entities] == [
        ("ability", "/api/v1/assets/dota/abilities/5442.png")
    ]


def test_presentation_rebuilds_names_when_same_patch_repository_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_a = tmp_path / "source-a"
    source_a.mkdir()
    catalog_files = (
        "manifest.json",
        "dota2_heroes.json",
        "dota2_abilities.json",
        "dota2_items.json",
        "sync_audit.json",
    )
    for filename in catalog_files:
        shutil.copyfile(CATALOG_DIR / filename, source_a / filename)

    source_b = tmp_path / "source-b"
    shutil.copytree(source_a, source_b)
    hero_path = source_b / "dota2_heroes.json"
    heroes = json.loads(hero_path.read_text(encoding="utf-8"))
    next(hero for hero in heroes if hero["hero_id"] == 18)["name_en"] = (
        "Sven Presentation Snapshot B"
    )
    hero_path.write_text(json.dumps(heroes, ensure_ascii=False), encoding="utf-8")

    store = CatalogSnapshotStore(tmp_path / "persistent-data")
    first = store.publish_from_directory(source_a)
    second = store.publish_from_directory(source_b)
    assert first.repository.snapshot_metadata()["patch"] == (
        second.repository.snapshot_metadata()["patch"]
    )

    image_root = tmp_path / "images"
    hero_image = image_root / "images" / "heroes" / "18.png"
    hero_image.parent.mkdir(parents=True)
    hero_image.write_bytes(b"local image")
    monkeypatch.setattr(presentation, "CATALOG_DIR", image_root)

    current = [first.repository]
    provider_calls = 0

    def repository_provider():
        nonlocal provider_calls
        provider_calls += 1
        return current[0]

    enricher = DotaVisualEntityEnricher(repository_provider)
    first_name = first.repository.get_hero(18).name_en
    assert any(entity.kind == "hero" for entity in enricher.match(first_name))

    current[0] = second.repository
    assert enricher.match(first_name) == []
    matches = enricher.match("Sven Presentation Snapshot B")

    assert len(matches) == 1
    assert matches[0].kind == "hero"
    assert "Sven Presentation Snapshot B" in matches[0].names
    assert provider_calls == 3
