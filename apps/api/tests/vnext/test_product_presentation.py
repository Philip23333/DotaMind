"""Deterministic local-catalog enrichment tests for product chat presentation."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from app.integrations.valve.catalog_repository import (
    CATALOG_DIR,
    load_default_catalog_repository,
)
from app.vnext.data_updates.catalog_store import CatalogSnapshotStore
from app.vnext.data_updates.image_reader import ImageManifestReader
from app.vnext.product import presentation
from app.vnext.product.presentation import DotaVisualEntityEnricher

_PNG_A = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082"
)
_PNG_B = _PNG_A + b"content version B"


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


def _write_persistent_hero_manifest(
    data_dir: Path,
    *,
    internal_name: str,
    payload: bytes,
    source_patch: str = "stale-source-patch",
) -> str:
    content_hash = hashlib.sha256(payload).hexdigest()
    images = data_dir / "images"
    assets = images / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / f"{content_hash}.png").write_bytes(payload)
    (images / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {
                    "heroes:18": {
                        "kind": "heroes",
                        "entity_id": 18,
                        "internal_name": internal_name,
                        "content_sha256": content_hash,
                        "source_patch": source_patch,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return content_hash


def test_persistent_manifest_uses_hash_url_without_requiring_current_patch(
    tmp_path: Path,
) -> None:
    repository = load_default_catalog_repository()
    hero = repository.get_hero(18)
    content_hash = _write_persistent_hero_manifest(
        tmp_path,
        internal_name=hero.internal_name,
        payload=_PNG_A,
    )
    enricher = DotaVisualEntityEnricher(
        lambda: repository,
        ImageManifestReader(tmp_path),
    )

    matches = enricher.match(hero.name_en)

    assert len(matches) == 1
    assert matches[0].imagePath == f"/api/v1/assets/dota/by-hash/{content_hash}.png"


def test_manifest_replacement_changes_next_match_with_same_catalog(
    tmp_path: Path,
) -> None:
    repository = load_default_catalog_repository()
    hero = repository.get_hero(18)
    first_hash = _write_persistent_hero_manifest(
        tmp_path,
        internal_name=hero.internal_name,
        payload=_PNG_A,
    )
    reader = ImageManifestReader(tmp_path)
    enricher = DotaVisualEntityEnricher(lambda: repository, reader)

    first = enricher.match(hero.name_en)
    second_hash = _write_persistent_hero_manifest(
        tmp_path,
        internal_name=hero.internal_name,
        payload=_PNG_B,
    )
    second = enricher.match(hero.name_en)

    assert first[0].imagePath == f"/api/v1/assets/dota/by-hash/{first_hash}.png"
    assert second[0].imagePath == f"/api/v1/assets/dota/by-hash/{second_hash}.png"
    assert first_hash != second_hash


def test_corrupt_replacement_retains_last_good_picture_metadata(tmp_path: Path) -> None:
    repository = load_default_catalog_repository()
    hero = repository.get_hero(18)
    content_hash = _write_persistent_hero_manifest(
        tmp_path,
        internal_name=hero.internal_name,
        payload=_PNG_A,
    )
    reader = ImageManifestReader(tmp_path)
    enricher = DotaVisualEntityEnricher(lambda: repository, reader)
    expected = f"/api/v1/assets/dota/by-hash/{content_hash}.png"
    assert enricher.match(hero.name_en)[0].imagePath == expected

    (tmp_path / "images" / "manifest.json").write_text("broken", encoding="utf-8")

    assert enricher.match(hero.name_en)[0].imagePath == expected


@pytest.mark.parametrize(
    ("manifest_internal_name", "write_asset"),
    [("old_internal_name", True), ("npc_dota_hero_sven", False)],
)
def test_mismatched_name_or_missing_asset_omits_persistent_visual(
    tmp_path: Path,
    manifest_internal_name: str,
    write_asset: bool,
) -> None:
    repository = load_default_catalog_repository()
    hero = repository.get_hero(18)
    content_hash = hashlib.sha256(_PNG_A).hexdigest()
    images = tmp_path / "images"
    assets = images / "assets"
    assets.mkdir(parents=True)
    if write_asset:
        (assets / f"{content_hash}.png").write_bytes(_PNG_A)
    (images / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {
                    "heroes:18": {
                        "kind": "heroes",
                        "entity_id": 18,
                        "internal_name": manifest_internal_name,
                        "content_sha256": content_hash,
                        "source_patch": "old-patch",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    entities = DotaVisualEntityEnricher(
        lambda: repository,
        ImageManifestReader(tmp_path),
    ).match(hero.name_en)

    assert not any(entity.kind == "hero" for entity in entities)


def test_manifest_and_catalog_are_each_fixed_once_per_match(tmp_path: Path) -> None:
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
    next(hero for hero in heroes if hero["hero_id"] == 18)["name_en"] = "Sven Image Snapshot B"
    hero_path.write_text(json.dumps(heroes, ensure_ascii=False), encoding="utf-8")

    store = CatalogSnapshotStore(tmp_path / "persistent-data")
    first_snapshot = store.publish_from_directory(source_a)
    second_snapshot = store.publish_from_directory(source_b)
    data_dir = tmp_path / "persistent-data"
    first_hash = _write_persistent_hero_manifest(
        data_dir,
        internal_name=first_snapshot.repository.get_hero(18).internal_name,
        payload=_PNG_A,
    )
    first_image_snapshot = ImageManifestReader(data_dir).read_current()
    second_hash = _write_persistent_hero_manifest(
        data_dir,
        internal_name=second_snapshot.repository.get_hero(18).internal_name,
        payload=_PNG_B,
    )
    second_image_snapshot = ImageManifestReader(data_dir).read_current()

    current_repository = [first_snapshot.repository]
    repository_calls = 0

    def repository_provider():
        nonlocal repository_calls
        repository_calls += 1
        selected = current_repository[0]
        current_repository[0] = second_snapshot.repository
        return selected

    class SwitchingReader:
        def __init__(self) -> None:
            self.calls = 0

        def read_current(self):
            self.calls += 1
            return (first_image_snapshot, second_image_snapshot)[self.calls - 1]

    reader = SwitchingReader()
    enricher = DotaVisualEntityEnricher(repository_provider, reader)  # type: ignore[arg-type]

    first_name = first_snapshot.repository.get_hero(18).name_en
    second_name = second_snapshot.repository.get_hero(18).name_en
    first = enricher.match(first_name)
    second = enricher.match(second_name)

    assert first[0].imagePath == f"/api/v1/assets/dota/by-hash/{first_hash}.png"
    assert second[0].imagePath == f"/api/v1/assets/dota/by-hash/{second_hash}.png"
    assert repository_calls == reader.calls == 2
