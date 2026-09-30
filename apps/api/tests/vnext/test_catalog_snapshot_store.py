from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from app.integrations.valve.catalog_repository import CATALOG_DIR, DotaCatalogRepository
from app.vnext.data_updates import catalog_store
from app.vnext.data_updates.catalog_store import CatalogSnapshotStore, CatalogStoreError

_CATALOG_FILES = (
    "manifest.json",
    "dota2_heroes.json",
    "dota2_abilities.json",
    "dota2_items.json",
    "sync_audit.json",
)


def _copy_catalog_source(destination: Path) -> Path:
    destination.mkdir(parents=True)
    for filename in _CATALOG_FILES:
        shutil.copyfile(CATALOG_DIR / filename, destination / filename)
    return destination


def _file_bytes(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _published_store(tmp_path: Path) -> tuple[CatalogSnapshotStore, Path]:
    source = _copy_catalog_source(tmp_path / "source")
    store = CatalogSnapshotStore(tmp_path / "persistent-data")
    store.publish_from_directory(source)
    return store, source


def _write_pointer(store: CatalogSnapshotStore, payload: bytes) -> None:
    pointer = store._current_pointer
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_bytes(payload)


def test_empty_store_has_no_current_snapshot(tmp_path: Path) -> None:
    assert CatalogSnapshotStore(tmp_path / "data").load_current() is None


def test_publish_copies_exact_files_and_repository_can_query_real_catalog(
    tmp_path: Path,
) -> None:
    source = _copy_catalog_source(tmp_path / "source")
    (source / "images").mkdir()
    (source / "images" / "18.png").write_bytes(b"optional image")
    (source / "notes.txt").write_text("not part of the catalog", encoding="utf-8")
    original_source = _file_bytes(source)
    expected_repository = DotaCatalogRepository(CATALOG_DIR)
    store = CatalogSnapshotStore(tmp_path / "persistent-data")

    published = store.publish_from_directory(source)
    loaded = store.load_current()

    assert loaded is not None
    assert loaded.revision == published.revision
    assert re.fullmatch(r"[0-9a-f]{32}", published.revision)
    assert published.directory == (
        tmp_path / "persistent-data" / "catalog" / "snapshots" / published.revision
    )
    assert set(path.name for path in published.directory.iterdir()) == set(_CATALOG_FILES)
    assert _file_bytes(published.directory) == {
        filename: original_source[filename] for filename in _CATALOG_FILES
    }
    assert _file_bytes(source) == original_source

    expected_sven = expected_repository.get_hero(18)
    assert published.repository.get_hero(18) == expected_sven
    ability_id = expected_sven.ability_ids[0]
    assert published.repository.get_ability(ability_id) == expected_repository.get_ability(
        ability_id
    )
    item_id = expected_repository.list_items()[0].item_id
    assert published.repository.get_item(item_id) == expected_repository.get_item(item_id)


def test_publish_switches_revision_and_keeps_old_repository_usable(tmp_path: Path) -> None:
    source = _copy_catalog_source(tmp_path / "source-first")
    store = CatalogSnapshotStore(tmp_path / "persistent-data")
    first = store.publish_from_directory(source)
    first_name = first.repository.get_hero(18).name_en

    second_source = _copy_catalog_source(tmp_path / "source-second")
    hero_path = second_source / "dota2_heroes.json"
    heroes = json.loads(hero_path.read_text(encoding="utf-8"))
    sven = next(hero for hero in heroes if hero["hero_id"] == 18)
    sven["name_en"] = f"{first_name} Snapshot Two"
    hero_path.write_text(json.dumps(heroes, ensure_ascii=False), encoding="utf-8")
    second = store.publish_from_directory(second_source)

    current = store.load_current()
    assert current is not None
    assert first.revision != second.revision
    assert current.revision == second.revision
    assert current.repository.get_hero(18).name_en == f"{first_name} Snapshot Two"
    assert first.repository.get_hero(18).name_en == first_name
    assert first.directory.is_dir()
    assert (first.directory / "dota2_heroes.json").is_file()
    assert first.repository.snapshot_metadata()["patch"] == second.repository.snapshot_metadata()[
        "patch"
    ]


@pytest.mark.parametrize("filename", _CATALOG_FILES)
def test_missing_source_file_does_not_change_current_pointer(
    tmp_path: Path, filename: str
) -> None:
    store, _ = _published_store(tmp_path)
    old_pointer = store._current_pointer.read_bytes()
    incomplete = _copy_catalog_source(tmp_path / "incomplete")
    (incomplete / filename).unlink()

    with pytest.raises(CatalogStoreError) as raised:
        store.publish_from_directory(incomplete)

    assert raised.value.reason == "invalid_snapshot"
    assert store._current_pointer.read_bytes() == old_pointer
    assert store.load_current() is not None


@pytest.mark.parametrize("damage", ["json", "catalog", "audit"])
def test_invalid_snapshot_does_not_change_current_pointer(
    tmp_path: Path, damage: str
) -> None:
    store, _ = _published_store(tmp_path)
    old_pointer = store._current_pointer.read_bytes()
    source = _copy_catalog_source(tmp_path / "damaged")

    if damage == "json":
        (source / "dota2_items.json").write_text("raw-secret {", encoding="utf-8")
    elif damage == "catalog":
        manifest_path = source / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["entity_counts"]["heroes"] += 1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    else:
        audit_path = source / "sync_audit.json"
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit["patch"] = "not-the-manifest-patch"
        audit_path.write_text(json.dumps(audit), encoding="utf-8")

    with pytest.raises(CatalogStoreError) as raised:
        store.publish_from_directory(source)

    assert raised.value.reason == "invalid_snapshot"
    assert "raw-secret" not in str(raised.value)
    assert store._current_pointer.read_bytes() == old_pointer
    assert store.load_current() is not None


@pytest.mark.parametrize("failure", ["copy", "rename", "pointer_replace"])
def test_storage_failures_keep_old_snapshot_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    store, _ = _published_store(tmp_path)
    old_pointer = store._current_pointer.read_bytes()
    source = _copy_catalog_source(tmp_path / "next-source")

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected storage failure")

    if failure == "copy":
        monkeypatch.setattr(catalog_store.shutil, "copyfile", fail)
    elif failure == "rename":
        monkeypatch.setattr(catalog_store.os, "rename", fail)
    else:
        monkeypatch.setattr(catalog_store.os, "replace", fail)

    with pytest.raises(CatalogStoreError) as raised:
        store.publish_from_directory(source)

    assert raised.value.reason == "storage_error"
    monkeypatch.undo()
    assert store._current_pointer.read_bytes() == old_pointer
    current = store.load_current()
    assert current is not None
    assert current.revision == json.loads(old_pointer)["revision"]


def test_current_pointer_changes_only_at_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _published_store(tmp_path)
    first = store.load_current()
    assert first is not None
    source = _copy_catalog_source(tmp_path / "next-source")
    original_replace = catalog_store.os.replace
    observed: list[str] = []

    def inspect_replace(source_path: str | Path, target_path: str | Path) -> None:
        before = store.load_current()
        assert before is not None and before.revision == first.revision
        replacement_revision = json.loads(Path(source_path).read_bytes())["revision"]
        original_replace(source_path, target_path)
        after = store.load_current()
        assert after is not None and after.revision == replacement_revision
        observed.append(replacement_revision)

    monkeypatch.setattr(catalog_store.os, "replace", inspect_replace)
    published = store.publish_from_directory(source)
    assert observed == [published.revision]


@pytest.mark.parametrize(
    "pointer_bytes",
    [
        b'{"schema_version":1,"revision":"../outside"}',
        b'{"schema_version":true,"revision":"a"}',
        b'{"schema_version":2,"revision":"00000000000000000000000000000000"}',
        b'{"schema_version":1,"revision":"00000000000000000000000000000000","extra":1}',
        b"malformed-pointer",
    ],
)
def test_invalid_pointer_is_rejected_without_loading_a_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pointer_bytes: bytes,
) -> None:
    store = CatalogSnapshotStore(tmp_path / "data")
    _write_pointer(store, pointer_bytes)

    def fail_if_loaded(*_args: object, **_kwargs: object) -> None:
        pytest.fail("an invalid pointer must be rejected before repository loading")

    monkeypatch.setattr(catalog_store, "DotaCatalogRepository", fail_if_loaded)
    with pytest.raises(CatalogStoreError) as raised:
        store.load_current()
    assert raised.value.reason == "invalid_pointer"


def test_pointer_to_missing_snapshot_is_an_invalid_snapshot(tmp_path: Path) -> None:
    store = CatalogSnapshotStore(tmp_path / "data")
    revision = "a" * 32
    _write_pointer(
        store,
        json.dumps({"schema_version": 1, "revision": revision}).encode("utf-8"),
    )

    with pytest.raises(CatalogStoreError) as raised:
        store.load_current()
    assert raised.value.reason == "invalid_snapshot"


def test_pointer_read_permission_error_is_a_storage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = CatalogSnapshotStore(tmp_path / "data")
    _write_pointer(
        store,
        json.dumps({"schema_version": 1, "revision": "a" * 32}).encode("utf-8"),
    )
    original_read_bytes = Path.read_bytes

    def fail_pointer_read(path: Path) -> bytes:
        if path == store._current_pointer:
            raise PermissionError("injected permission error")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_pointer_read)
    with pytest.raises(CatalogStoreError) as raised:
        store.load_current()
    assert raised.value.reason == "storage_error"


def test_read_current_revision_returns_none_without_pointer(tmp_path: Path) -> None:
    store = CatalogSnapshotStore(tmp_path / "data")
    assert store.read_current_revision() is None


def test_read_current_revision_only_reads_validated_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _published_store(tmp_path)
    expected_revision = store.load_current().revision  # type: ignore[union-attr]

    def fail_if_snapshot_loaded(*_args: object, **_kwargs: object) -> None:
        pytest.fail("revision-only reads must not load snapshot files or a repository")

    monkeypatch.setattr(catalog_store, "DotaCatalogRepository", fail_if_snapshot_loaded)
    monkeypatch.setattr(
        store,
        "_validate_snapshot_directory",
        fail_if_snapshot_loaded,
    )
    assert store.read_current_revision() == expected_revision


def test_read_current_revision_reuses_invalid_pointer_error(
    tmp_path: Path,
) -> None:
    store = CatalogSnapshotStore(tmp_path / "data")
    _write_pointer(store, b'{"schema_version":1,"revision":"../outside"}')

    with pytest.raises(CatalogStoreError) as raised:
        store.read_current_revision()
    assert raised.value.reason == "invalid_pointer"


def test_read_current_revision_io_error_is_storage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = CatalogSnapshotStore(tmp_path / "data")
    _write_pointer(
        store,
        json.dumps({"schema_version": 1, "revision": "a" * 32}).encode("utf-8"),
    )
    original_read_bytes = Path.read_bytes

    def fail_pointer_read(path: Path) -> bytes:
        if path == store._current_pointer:
            raise PermissionError("injected permission error")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_pointer_read)
    with pytest.raises(CatalogStoreError) as raised:
        store.read_current_revision()
    assert raised.value.reason == "storage_error"
