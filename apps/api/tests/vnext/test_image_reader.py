from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.vnext.data_updates.image_reader import ImageManifestReader

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082"
)


def _write_manifest(
    data_root: Path,
    *,
    content: bytes = _PNG,
    internal_name: str = "npc_dota_hero_sven",
    source_patch: str = "old-patch",
) -> str:
    content_hash = hashlib.sha256(content).hexdigest()
    images = data_root / "images"
    assets = images / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / f"{content_hash}.png").write_bytes(content)
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


def test_reader_returns_content_hash_url_and_allows_old_source_patch(tmp_path: Path) -> None:
    content_hash = _write_manifest(tmp_path, source_patch="older-catalog-patch")
    reader = ImageManifestReader(tmp_path)

    snapshot = reader.read_current()

    assert snapshot.image_url(
        kind="hero",
        entity_id=18,
        internal_name="npc_dota_hero_sven",
    ) == f"/api/v1/assets/dota/by-hash/{content_hash}.png"
    assert snapshot.image_url(
        kind="item",
        entity_id=18,
        internal_name="npc_dota_hero_sven",
    ) is None


def test_missing_or_initially_corrupt_manifest_yields_empty_snapshot(tmp_path: Path) -> None:
    reader = ImageManifestReader(tmp_path)

    missing = reader.read_current()
    assert dict(missing.entries) == {}

    manifest = tmp_path / "images" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{broken", encoding="utf-8")
    corrupt = reader.read_current()
    assert dict(corrupt.entries) == {}
    assert corrupt.image_url(
        kind="hero",
        entity_id=18,
        internal_name="npc_dota_hero_sven",
    ) is None


def test_corrupt_or_missing_later_manifest_keeps_last_valid_snapshot(tmp_path: Path) -> None:
    content_hash = _write_manifest(tmp_path)
    reader = ImageManifestReader(tmp_path)
    valid = reader.read_current()
    manifest = tmp_path / "images" / "manifest.json"

    manifest.write_text("{broken", encoding="utf-8")
    assert reader.read_current() is valid

    manifest.unlink()
    assert reader.read_current() is valid
    assert valid.image_url(
        kind="hero",
        entity_id=18,
        internal_name="npc_dota_hero_sven",
    ) == f"/api/v1/assets/dota/by-hash/{content_hash}.png"


def test_missing_asset_and_mismatched_internal_name_do_not_resolve(tmp_path: Path) -> None:
    content_hash = _write_manifest(tmp_path, internal_name="old_hero_internal_name")
    snapshot = ImageManifestReader(tmp_path).read_current()
    assert snapshot.image_url(
        kind="hero",
        entity_id=18,
        internal_name="npc_dota_hero_sven",
    ) is None

    (tmp_path / "images" / "assets" / f"{content_hash}.png").unlink()
    assert ImageManifestReader(tmp_path).read_current().image_url(
        kind="hero",
        entity_id=18,
        internal_name="old_hero_internal_name",
    ) is None


def test_reader_does_not_modify_the_data_directory(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    before = {
        path.relative_to(tmp_path): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    reader = ImageManifestReader(tmp_path)
    reader.read_current()
    reader.read_current()

    after = {
        path.relative_to(tmp_path): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
