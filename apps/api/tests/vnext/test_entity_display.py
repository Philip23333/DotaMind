from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.integrations.valve.catalog_repository import (
    DotaCatalogRepository,
    load_default_catalog_repository,
)
from app.vnext.data_updates.image_reader import ImageManifestReader
from app.vnext.entity_display import (
    EntityDisplayDirectory,
    EntityIdentity,
    make_display_ref,
    parse_display_ref,
)

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082"
)


def _identity(kind: str, entity_id: int) -> EntityIdentity:
    source = "pandascore" if kind == "team" else "valve"
    return EntityIdentity(source=source, kind=kind, entity_id=entity_id)  # type: ignore[arg-type]


def _write_team_snapshot(
    data_root: Path,
    teams: list[dict[str, object]],
) -> None:
    directory = data_root / "display"
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "teams": {str(team["source_id"]): team for team in teams},
    }
    (directory / "teams.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _team(
    source_id: int,
    label: str,
    *,
    image_asset: str | None = None,
    acronym: str = "BB",
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "label": label,
        "acronym": acronym,
        "observed_image_url": f"https://example.invalid/{source_id}.png",
        "downloaded_image_url": f"https://example.invalid/{source_id}.png"
        if image_asset
        else None,
        "image_asset": image_asset,
        "image_downloaded_at": "2026-10-01T00:00:00Z" if image_asset else None,
        "monthly_refresh_completed": "2026-10" if image_asset else None,
    }


def _write_manifest(
    data_root: Path,
    catalog: DotaCatalogRepository,
    *,
    include: set[str],
) -> str:
    images = data_root / "images"
    assets = images / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    content_hash = hashlib.sha256(_PNG).hexdigest()
    (assets / f"{content_hash}.png").write_bytes(_PNG)

    entries: dict[str, dict[str, object]] = {}
    records: dict[str, tuple[int, str]] = {
        "hero": (catalog.list_heroes()[0].hero_id, catalog.list_heroes()[0].internal_name),
        "item": (catalog.list_items()[0].item_id, catalog.list_items()[0].internal_name),
        "ability": (
            catalog.list_abilities()[0].ability_id,
            catalog.list_abilities()[0].internal_name,
        ),
    }
    manifest_kinds = {"hero": "heroes", "item": "items", "ability": "abilities"}
    for kind in include:
        entity_id, internal_name = records[kind]
        manifest_kind = manifest_kinds[kind]
        entries[f"{manifest_kind}:{entity_id}"] = {
            "kind": manifest_kind,
            "entity_id": entity_id,
            "internal_name": internal_name,
            "content_sha256": content_hash,
            "source_patch": "test-patch",
        }
    images.joinpath("manifest.json").write_text(
        json.dumps({"schema_version": 1, "entries": entries}),
        encoding="utf-8",
    )
    return content_hash


def test_reference_syntax_accepts_only_canonical_supported_combinations() -> None:
    identities = (
        EntityIdentity("valve", "hero", 14),
        EntityIdentity("valve", "item", 1),
        EntityIdentity("valve", "ability", 730),
        EntityIdentity("pandascore", "team", 139340),
    )
    for identity in identities:
        ref = make_display_ref(identity)
        assert parse_display_ref(ref) == identity

    for ref in (
        "display:valve:player:1",
        "display:pandascore:hero:1",
        "display:valve:team:1",
        "display:unknown:team:1",
        "display:valve:hero:0",
        "display:valve:hero:014",
        "display:valve:hero:+14",
        "display:valve:hero:14/",
    ):
        assert parse_display_ref(ref) is None

    with pytest.raises(ValueError):
        EntityIdentity("valve", "hero", True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        EntityIdentity("pandascore", "player", 1)  # type: ignore[arg-type]


def test_explicit_ids_resolve_catalog_entities_and_same_acronym_teams(
    tmp_path: Path,
) -> None:
    repository = load_default_catalog_repository()
    _write_team_snapshot(
        tmp_path,
        [_team(101, "BetBoom Team"), _team(202, "Black Box" )],
    )
    directory = EntityDisplayDirectory(lambda: repository, data_root=tmp_path)
    hero = repository.list_heroes()[0]
    item = repository.list_items()[0]
    ability = repository.list_abilities()[0]

    identities = (
        _identity("hero", hero.hero_id),
        _identity("item", item.item_id),
        _identity("ability", ability.ability_id),
        _identity("team", 101),
        _identity("team", 202),
    )
    refs = [directory.reference_for(identity) for identity in identities]
    assert all(ref is not None for ref in refs)
    resolved = directory.resolve_many(ref for ref in refs if ref is not None)

    assert len(resolved) == 5
    assert resolved[make_display_ref(identities[0])].label == (
        hero.name_zh or hero.name_en or hero.internal_name
    )
    assert resolved[make_display_ref(identities[1])].label == (
        item.name_zh or item.name_en or item.internal_name
    )
    assert resolved[make_display_ref(identities[2])].label == (
        ability.name_zh or ability.name_en or ability.internal_name
    )
    assert resolved[make_display_ref(identities[3])].label == "BetBoom Team"
    assert resolved[make_display_ref(identities[4])].label == "Black Box"
    assert directory.reference_for(_identity("team", 303)) is None
    assert directory.reference_for(_identity("hero", 999999999)) is None
    assert directory.resolve_many(["display:valve:hero:999999999"]) == {}


def test_missing_images_do_not_hide_existing_catalog_or_team_entities(
    tmp_path: Path,
) -> None:
    repository = load_default_catalog_repository()
    hero = repository.list_heroes()[0]
    ability = next(
        (
            record
            for record in repository.list_abilities()
            if not record.name_zh and not record.name_en
        ),
        repository.list_abilities()[0],
    )
    _write_manifest(tmp_path, repository, include=set())
    _write_team_snapshot(tmp_path, [_team(101, "BetBoom Team", image_asset="a" * 64)])
    directory = EntityDisplayDirectory(lambda: repository, data_root=tmp_path)

    hero_ref = directory.reference_for(_identity("hero", hero.hero_id))
    ability_ref = directory.reference_for(_identity("ability", ability.ability_id))
    team_ref = directory.reference_for(_identity("team", 101))
    resolved = directory.resolve_many(
        ref for ref in (hero_ref, ability_ref, team_ref) if ref is not None
    )

    assert hero_ref is not None and resolved[hero_ref].label
    assert resolved[hero_ref].image_url is None
    assert ability_ref is not None and resolved[ability_ref].label
    assert resolved[ability_ref].image_url is None
    assert team_ref is not None and resolved[team_ref].label == "BetBoom Team"
    assert resolved[team_ref].image_url is None


def test_missing_team_snapshot_is_empty_without_affecting_valve_resolution(
    tmp_path: Path,
) -> None:
    repository = load_default_catalog_repository()
    hero = repository.list_heroes()[0]
    directory = EntityDisplayDirectory(lambda: repository, data_root=tmp_path)

    assert directory.reference_for(_identity("team", 101)) is None
    assert directory.reference_for(_identity("hero", hero.hero_id)) is not None


def test_batch_uses_one_catalog_and_one_image_manifest_snapshot(tmp_path: Path) -> None:
    repository = load_default_catalog_repository()
    _write_manifest(tmp_path, repository, include={"hero", "item", "ability"})
    hero = repository.list_heroes()[0]
    item = repository.list_items()[0]
    ability = repository.list_abilities()[0]
    provider_calls = 0

    def provide_catalog() -> DotaCatalogRepository:
        nonlocal provider_calls
        provider_calls += 1
        return repository

    class CountingImageReader:
        def __init__(self) -> None:
            self.reader = ImageManifestReader(tmp_path)
            self.calls = 0

        def read_current(self) -> Any:
            self.calls += 1
            return self.reader.read_current()

    image_reader = CountingImageReader()
    directory = EntityDisplayDirectory(
        provide_catalog,
        data_root=tmp_path,
        image_manifest_reader=image_reader,  # type: ignore[arg-type]
    )
    refs = [
        make_display_ref(_identity("hero", hero.hero_id)),
        make_display_ref(_identity("item", item.item_id)),
        make_display_ref(_identity("ability", ability.ability_id)),
    ]
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    resolved = directory.resolve_many([refs[0], refs[1], refs[0], refs[2]])

    assert list(resolved) == refs
    assert all(entity.image_url is not None for entity in resolved.values())
    assert provider_calls == 1
    assert image_reader.calls == 1
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_team_snapshot_switches_and_corruption_keeps_last_valid_file(
    tmp_path: Path,
) -> None:
    repository = load_default_catalog_repository()
    _write_team_snapshot(tmp_path, [_team(101, "Old Team Label")])
    directory = EntityDisplayDirectory(lambda: repository, data_root=tmp_path)
    team_ref = "display:pandascore:team:101"

    assert directory.resolve_many([team_ref])[team_ref].label == "Old Team Label"
    _write_team_snapshot(tmp_path, [_team(101, "New Team Label")])
    assert directory.resolve_many([team_ref])[team_ref].label == "New Team Label"

    (tmp_path / "display" / "teams.json").write_text("{broken", encoding="utf-8")
    assert directory.resolve_many([team_ref])[team_ref].label == "New Team Label"


def test_team_image_uses_shared_content_hash_route_only_when_file_exists(
    tmp_path: Path,
) -> None:
    repository = load_default_catalog_repository()
    content_hash = hashlib.sha256(_PNG).hexdigest()
    _write_team_snapshot(
        tmp_path,
        [_team(101, "BetBoom Team", image_asset=content_hash)],
    )
    directory = EntityDisplayDirectory(lambda: repository, data_root=tmp_path)
    team_ref = "display:pandascore:team:101"

    assert directory.resolve_many([team_ref])[team_ref].image_url is None
    assets = tmp_path / "images" / "assets"
    assets.mkdir(parents=True)
    (assets / f"{content_hash}.png").write_bytes(_PNG)
    assert directory.resolve_many([team_ref])[team_ref].image_url == (
        f"/api/v1/assets/dota/by-hash/{content_hash}.png"
    )
