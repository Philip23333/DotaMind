from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.integrations.valve import game_data_sync
from app.integrations.valve.catalog_repository import CATALOG_DIR, DotaCatalogRepository
from app.vnext.data_updates.catalog_refresh import refresh_catalog
from app.vnext.data_updates.catalog_store import CatalogSnapshotStore, CatalogStoreError


class FakeSession:
    pass


def _bundle_for_patch(patch: str):
    source = game_data_sync._load_committed_catalog_bundle()
    manifest = source.manifest.model_copy(
        update={"patch": patch, "generated_at": source.manifest.generated_at}
    )
    assert source.sync_audit is not None
    audit = source.sync_audit.model_copy(
        update={"patch": patch, "generated_at": source.sync_audit.generated_at}
    )
    return source.model_copy(update={"manifest": manifest, "sync_audit": audit})


def _seed(data_root: Path):
    return CatalogSnapshotStore(data_root).publish_from_directory(CATALOG_DIR)


def _patch_latest(monkeypatch: pytest.MonkeyPatch, patch: str, calls: list[object]):
    def latest(session):
        calls.append(session)
        return patch

    monkeypatch.setattr(game_data_sync, "_latest_patch", latest)


def _patch_builder(monkeypatch: pytest.MonkeyPatch, calls: list[tuple[object, str, int]]):
    def build(session, patch: str, *, workers: int = 8, generated_at=None):
        calls.append((session, patch, workers))
        return _bundle_for_patch(patch)

    monkeypatch.setattr(game_data_sync, "_build_catalog_snapshot", build)


def test_same_patch_checks_remote_only_and_preserves_current_files(tmp_path, monkeypatch) -> None:
    current = _seed(tmp_path)
    before_pointer = (tmp_path / "catalog" / "current.json").read_bytes()
    before_files = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in current.directory.iterdir()
    }
    latest_calls: list[object] = []
    build_calls: list[tuple[object, str, int]] = []
    _patch_latest(monkeypatch, current.repository.manifest.patch, latest_calls)
    _patch_builder(monkeypatch, build_calls)
    session = FakeSession()

    report = refresh_catalog(data_root=tmp_path, session=session)

    assert report.action == "skipped"
    assert report.reason == "patch_unchanged"
    assert report.previous_patch == report.target_patch == current.repository.manifest.patch
    assert report.revision == current.revision
    assert latest_calls == [session]
    assert build_calls == []
    assert (tmp_path / "catalog" / "current.json").read_bytes() == before_pointer
    assert {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in current.directory.iterdir()
    } == before_files


def test_changed_patch_publishes_complete_new_revision_and_keeps_old(tmp_path, monkeypatch) -> None:
    old = _seed(tmp_path)
    target_patch = "99.1"
    session = FakeSession()
    latest_calls: list[object] = []
    build_calls: list[tuple[object, str, int]] = []
    _patch_latest(monkeypatch, target_patch, latest_calls)
    _patch_builder(monkeypatch, build_calls)

    report = refresh_catalog(data_root=tmp_path, session=session, workers=3)

    assert report.action == "updated"
    assert report.reason == "patch_changed"
    assert report.previous_patch == old.repository.manifest.patch
    assert report.target_patch == target_patch
    assert report.revision != old.revision
    assert latest_calls == [session]
    assert build_calls == [(session, target_patch, 3)]
    loaded = CatalogSnapshotStore(tmp_path).load_current()
    assert loaded is not None
    assert loaded.revision == report.revision
    assert loaded.repository.manifest.patch == target_patch
    assert DotaCatalogRepository(loaded.directory).manifest.patch == target_patch
    assert old.directory.is_dir()
    assert set(path.name for path in loaded.directory.iterdir()) == {
        "manifest.json",
        "dota2_heroes.json",
        "dota2_abilities.json",
        "dota2_items.json",
        "sync_audit.json",
    }


def test_force_refreshes_even_when_patch_is_unchanged(tmp_path, monkeypatch) -> None:
    old = _seed(tmp_path)
    latest_calls: list[object] = []
    build_calls: list[tuple[object, str, int]] = []
    _patch_latest(monkeypatch, old.repository.manifest.patch, latest_calls)
    _patch_builder(monkeypatch, build_calls)

    report = refresh_catalog(data_root=tmp_path, session=FakeSession(), force=True)

    assert report.action == "updated"
    assert report.reason == "forced"
    assert report.revision != old.revision
    assert len(latest_calls) == 1
    assert build_calls[0][1] == old.repository.manifest.patch


def test_missing_local_snapshot_can_be_initialized(tmp_path, monkeypatch) -> None:
    latest_calls: list[object] = []
    build_calls: list[tuple[object, str, int]] = []
    _patch_latest(monkeypatch, "99.2", latest_calls)
    _patch_builder(monkeypatch, build_calls)

    report = refresh_catalog(data_root=tmp_path, session=FakeSession())

    assert report.action == "updated"
    assert report.reason == "missing"
    assert report.previous_patch is None
    assert CatalogSnapshotStore(tmp_path).load_current().revision == report.revision
    assert not list((tmp_path / "catalog").glob(".refresh-catalog-*"))


@pytest.mark.parametrize("corruption", ["pointer", "snapshot"])
def test_invalid_local_state_is_repaired_after_successful_update(
    tmp_path, monkeypatch, corruption: str
) -> None:
    old = _seed(tmp_path)
    if corruption == "pointer":
        (tmp_path / "catalog" / "current.json").write_text("{", encoding="utf-8")
    else:
        current_dir = tmp_path / "catalog" / "snapshots" / old.revision
        (current_dir / "manifest.json").write_bytes(b"not json")
    latest_calls: list[object] = []
    build_calls: list[tuple[object, str, int]] = []
    _patch_latest(monkeypatch, "99.3", latest_calls)
    _patch_builder(monkeypatch, build_calls)

    report = refresh_catalog(data_root=tmp_path, session=FakeSession())

    assert report.action == "updated"
    assert report.reason == "invalid_local"
    assert report.previous_patch is None
    loaded = CatalogSnapshotStore(tmp_path).load_current()
    assert loaded is not None
    assert loaded.revision == report.revision
    assert loaded.repository.manifest.patch == "99.3"
    assert old.directory.is_dir()


def test_local_storage_error_stops_before_remote_patch_check(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        CatalogSnapshotStore,
        "load_current",
        lambda _self: (_ for _ in ()).throw(CatalogStoreError("storage_error")),
    )
    latest_calls: list[object] = []
    _patch_latest(monkeypatch, "99.4", latest_calls)

    with pytest.raises(CatalogStoreError, match="storage operation failed"):
        refresh_catalog(data_root=tmp_path, session=FakeSession())
    assert latest_calls == []
    monkeypatch.undo()
    assert CatalogSnapshotStore(tmp_path).load_current() is None


def test_remote_patch_check_failure_never_means_skip(tmp_path, monkeypatch) -> None:
    old = _seed(tmp_path)

    def fail(_session):
        raise RuntimeError("remote failed")

    monkeypatch.setattr(game_data_sync, "_latest_patch", fail)
    with pytest.raises(RuntimeError, match="remote failed"):
        refresh_catalog(data_root=tmp_path, session=FakeSession())
    assert (tmp_path / "catalog" / "current.json").read_bytes() == json.dumps(
        {"schema_version": 1, "revision": old.revision}, separators=(",", ":")
    ).encode() + b"\n"


def test_failed_update_is_retried_on_the_next_invocation(tmp_path, monkeypatch) -> None:
    old = _seed(tmp_path)
    latest_calls: list[object] = []
    _patch_latest(monkeypatch, "99.5", latest_calls)
    attempts = 0

    def fail_once(session, patch: str, *, workers: int = 8, generated_at=None):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary build failure")
        return _bundle_for_patch(patch)

    monkeypatch.setattr(game_data_sync, "_build_catalog_snapshot", fail_once)
    session = FakeSession()
    with pytest.raises(RuntimeError, match="temporary build failure"):
        refresh_catalog(data_root=tmp_path, session=session)
    pointer = json.loads((tmp_path / "catalog" / "current.json").read_text())
    assert pointer["revision"] == old.revision

    report = refresh_catalog(data_root=tmp_path, session=session)
    assert report.reason == "patch_changed"
    assert attempts == 2
    assert latest_calls == [session, session]
    assert report.revision != old.revision


@pytest.mark.parametrize("failure", ["serialization", "publication"])
def test_serialization_or_publication_failure_preserves_current_and_cleans_temp(
    tmp_path, monkeypatch, failure: str
) -> None:
    old = _seed(tmp_path)
    _patch_latest(monkeypatch, "99.6", [])
    _patch_builder(monkeypatch, [])
    if failure == "serialization":
        monkeypatch.setattr(
            game_data_sync,
            "serialize_catalog_bundle",
            lambda _bundle: (_ for _ in ()).throw(RuntimeError("serialize failed")),
        )
    else:
        monkeypatch.setattr(
            CatalogSnapshotStore,
            "publish_from_directory",
            lambda _self, _source: (_ for _ in ()).throw(
                CatalogStoreError("storage_error")
            ),
        )

    with pytest.raises((RuntimeError, CatalogStoreError)):
        refresh_catalog(data_root=tmp_path, session=FakeSession())

    pointer = json.loads((tmp_path / "catalog" / "current.json").read_text())
    assert pointer["revision"] == old.revision
    assert not list((tmp_path / "catalog").glob(".refresh-catalog-*"))
    assert old.directory.is_dir()


@pytest.mark.parametrize("workers", [True, 0, -1, 17, 2.0])
def test_refresh_rejects_invalid_worker_counts_before_any_catalog_io(tmp_path, workers) -> None:
    with pytest.raises(ValueError, match="workers"):
        refresh_catalog(data_root=tmp_path, session=FakeSession(), workers=workers)
    assert not (tmp_path / "catalog").exists()
