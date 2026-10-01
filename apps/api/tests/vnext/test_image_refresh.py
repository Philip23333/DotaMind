from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.integrations.valve.catalog_repository import CATALOG_DIR
from app.integrations.valve.image_client import PNG_SIGNATURE, ValveImageError
from app.vnext.data_updates import image_refresh
from app.vnext.data_updates.catalog_store import CatalogSnapshotStore
from app.vnext.data_updates.image_refresh import ImageRefreshError, refresh_images


def _entity(**values: Any) -> SimpleNamespace:
    return SimpleNamespace(**values)


def _repository(*, patch: str = "7.41f", hero_name: str = "npc_dota_hero_sven") -> Any:
    return SimpleNamespace(
        manifest=SimpleNamespace(patch=patch),
        list_heroes=lambda: [
            _entity(hero_id=18, internal_name=hero_name),
        ],
        list_items=lambda: [
            _entity(item_id=1, internal_name="item_blink", is_recipe=False),
            _entity(item_id=2, internal_name="item_recipe_blink", is_recipe=True),
        ],
        list_abilities=lambda: [
            _entity(
                ability_id=5094,
                internal_name="sven_storm_bolt",
                is_item=False,
                is_talent=False,
                is_innate=False,
                name_en="Storm Hammer",
                name_zh="风暴之拳",
            ),
            _entity(
                ability_id=10001,
                internal_name="item_blink",
                is_item=True,
                is_talent=False,
                is_innate=False,
                name_en="Blink",
                name_zh="闪烁匕首",
            ),
            _entity(
                ability_id=10002,
                internal_name="special_bonus_sven_1",
                is_item=False,
                is_talent=True,
                is_innate=False,
                name_en="Talent",
                name_zh="天赋",
            ),
            _entity(
                ability_id=10003,
                internal_name="sven_innate",
                is_item=False,
                is_talent=False,
                is_innate=True,
                name_en="Innate",
                name_zh="先天",
            ),
            _entity(
                ability_id=10004,
                internal_name="unnamed_ability",
                is_item=False,
                is_talent=False,
                is_innate=False,
                name_en="",
                name_zh="",
            ),
        ],
    )


class FakeStore:
    def __init__(self, data_root: Path, snapshot: Any | None) -> None:
        self.data_root = data_root
        self.snapshot = snapshot
        self.load_calls = 0

    def load_current(self) -> Any | None:
        self.load_calls += 1
        return self.snapshot


class FakeImageClient:
    def __init__(self, outcomes: dict[str, bytes | Exception] | None = None) -> None:
        self.outcomes = {} if outcomes is None else dict(outcomes)
        self.calls: list[tuple[str, str]] = []
        self.lock = threading.Lock()

    def fetch_png(self, kind: str, internal_name: str) -> bytes:
        with self.lock:
            self.calls.append((kind, internal_name))
        outcome = self.outcomes.get(internal_name, PNG_SIGNATURE + internal_name.encode())
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _install_store(
    monkeypatch: pytest.MonkeyPatch,
    data_root: Path,
    *,
    repository: Any | None = None,
) -> FakeStore:
    snapshot = None
    if repository is not None:
        snapshot = SimpleNamespace(
            revision="a" * 32,
            repository=repository,
        )
    store = FakeStore(data_root, snapshot)
    monkeypatch.setattr(image_refresh, "CatalogSnapshotStore", lambda root: store)
    return store


def _read_manifest(data_root: Path) -> dict[str, Any]:
    return json.loads((data_root / "images" / "manifest.json").read_text("utf-8"))


def test_first_refresh_persists_selected_pngs_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    store = _install_store(monkeypatch, data_root, repository=_repository())
    client = FakeImageClient()

    report = refresh_images(data_root=data_root, workers=2, client=client)

    manifest = _read_manifest(data_root)
    assert store.load_calls == 1
    assert report.catalog_revision == "a" * 32
    assert report.catalog_patch == "7.41f"
    assert (report.target_count, report.downloaded, report.skipped, report.failures) == (
        3,
        3,
        0,
        (),
    )
    assert {key for key in manifest["entries"]} == {
        "heroes:18",
        "items:1",
        "abilities:5094",
    }
    assert len(client.calls) == 3
    for _key, entry in manifest["entries"].items():
        assert set(entry) == {
            "kind",
            "entity_id",
            "internal_name",
            "content_sha256",
            "source_patch",
        }
        asset = data_root / "images" / "assets" / f"{entry['content_sha256']}.png"
        content = asset.read_bytes()
        assert content.startswith(PNG_SIGNATURE)
        assert hashlib.sha256(content).hexdigest() == entry["content_sha256"]
        assert entry["source_patch"] == "7.41f"
    assert not list((data_root / "images" / "assets").glob("*.tmp"))


def test_refresh_loads_a_real_static_catalog_snapshot_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    snapshot_store = CatalogSnapshotStore(data_root)
    snapshot_store.publish_from_directory(CATALOG_DIR)
    real_target_builder = image_refresh.game_data_sync._catalog_image_targets
    selected: list[Any] = []

    def one_real_hero_target(**kwargs: Any) -> list[Any]:
        targets = real_target_builder(**kwargs)
        selected.extend(targets[:1])
        return targets[:1]

    monkeypatch.setattr(
        image_refresh.game_data_sync,
        "_catalog_image_targets",
        one_real_hero_target,
    )
    client = FakeImageClient()

    report = refresh_images(data_root=data_root, client=client)

    stored = CatalogSnapshotStore(data_root).load_current()
    assert stored is not None
    assert report.catalog_revision == stored.revision
    assert report.catalog_patch == stored.repository.manifest.patch
    assert report.target_count == report.downloaded == 1
    assert len(selected) == len(client.calls) == 1
    manifest = _read_manifest(data_root)
    entry = manifest["entries"][f"heroes:{selected[0].entity_id}"]
    assert entry["internal_name"] == selected[0].internal_name
    assert entry["source_patch"] == stored.repository.manifest.patch


def test_current_assets_skip_download_and_manifest_is_not_rewritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    _install_store(monkeypatch, data_root, repository=_repository())
    refresh_images(data_root=data_root, client=FakeImageClient())
    manifest_path = data_root / "images" / "manifest.json"
    before = (manifest_path.read_bytes(), manifest_path.stat().st_mtime_ns)
    client = FakeImageClient()

    report = refresh_images(data_root=data_root, client=client)

    assert report.downloaded == 0
    assert report.skipped == report.target_count == 3
    assert not report.failures
    assert client.calls == []
    assert (manifest_path.read_bytes(), manifest_path.stat().st_mtime_ns) == before


def test_missing_or_hash_corrupt_asset_is_downloaded_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    _install_store(monkeypatch, data_root, repository=_repository())
    refresh_images(data_root=data_root, client=FakeImageClient())
    manifest = _read_manifest(data_root)
    hero_entry = manifest["entries"]["heroes:18"]
    hero_asset = data_root / "images" / "assets" / f"{hero_entry['content_sha256']}.png"
    hero_asset.unlink()
    item_entry = manifest["entries"]["items:1"]
    item_asset = data_root / "images" / "assets" / f"{item_entry['content_sha256']}.png"
    item_asset.write_bytes(b"damaged")
    client = FakeImageClient()

    report = refresh_images(data_root=data_root, client=client)

    assert report.downloaded == 2
    assert report.skipped == 1
    assert set(client.calls) == {
        ("heroes", "npc_dota_hero_sven"),
        ("items", "item_blink"),
    }


def test_name_patch_and_force_changes_request_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    current = {"repository": _repository()}
    _install_store(monkeypatch, data_root, repository=current["repository"])
    refresh_images(data_root=data_root, client=FakeImageClient())
    current["repository"] = _repository(patch="7.42", hero_name="npc_dota_hero_new_sven")
    monkeypatch.setattr(
        image_refresh,
        "CatalogSnapshotStore",
        lambda _root: FakeStore(
            data_root,
            SimpleNamespace(revision="b" * 32, repository=current["repository"]),
        ),
    )
    client = FakeImageClient()

    report = refresh_images(data_root=data_root, client=client)

    assert report.catalog_patch == "7.42"
    assert report.downloaded == report.target_count == 3
    assert {name for _kind, name in client.calls} == {
        "npc_dota_hero_new_sven",
        "item_blink",
        "sven_storm_bolt",
    }
    forced = FakeImageClient()
    force_report = refresh_images(data_root=data_root, force=True, client=forced)
    assert force_report.downloaded == force_report.target_count == 3
    assert len(forced.calls) == 3


def test_identical_content_reuses_one_hash_path_and_failed_fetch_preserves_old_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    _install_store(monkeypatch, data_root, repository=_repository())
    shared_png = PNG_SIGNATURE + b"same-content"
    refresh_images(
        data_root=data_root,
        client=FakeImageClient(
            {
                "npc_dota_hero_sven": shared_png,
                "item_blink": shared_png,
                "sven_storm_bolt": shared_png,
            }
        ),
    )
    initial = _read_manifest(data_root)
    assert len(list((data_root / "images" / "assets").glob("*.png"))) == 1
    old_hero = dict(initial["entries"]["heroes:18"])
    monkeypatch.setattr(
        image_refresh,
        "CatalogSnapshotStore",
        lambda _root: FakeStore(
            data_root,
            SimpleNamespace(revision="c" * 32, repository=_repository(patch="7.42")),
        ),
    )
    outcomes = {
        "npc_dota_hero_sven": ValveImageError("download_failed"),
        "item_blink": shared_png,
        "sven_storm_bolt": shared_png,
    }

    report = refresh_images(data_root=data_root, client=FakeImageClient(outcomes))

    updated = _read_manifest(data_root)
    assert report.downloaded == 2
    assert report.failures[0].kind == "heroes"
    assert report.failures[0].entity_id == 18
    assert updated["entries"]["heroes:18"] == old_hero
    assert updated["entries"]["heroes:18"]["source_patch"] == "7.41f"
    assert updated["entries"]["items:1"]["source_patch"] == "7.42"


def test_first_download_failure_adds_no_success_entry_and_preserves_unrelated_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    _install_store(monkeypatch, data_root, repository=_repository())
    patch_file = data_root / "patches" / "7_41f.json"
    patch_file.parent.mkdir(parents=True)
    patch_file.write_bytes(b"patch-record")
    guide_file = data_root / "guides" / "pub-18-1.json"
    guide_file.parent.mkdir(parents=True)
    guide_file.write_bytes(b"guide-record")
    historical_asset = data_root / "images" / "assets" / ("f" * 64 + ".png")
    historical_asset.parent.mkdir(parents=True)
    historical_asset.write_bytes(PNG_SIGNATURE + b"historical")
    client = FakeImageClient(
        {"npc_dota_hero_sven": ValveImageError("download_failed")}
    )

    report = refresh_images(data_root=data_root, client=client)

    manifest = _read_manifest(data_root)
    assert "heroes:18" not in manifest["entries"]
    assert report.target_count == report.downloaded + report.skipped + len(report.failures)
    assert report.failures[0].entity_id == 18
    assert patch_file.read_bytes() == b"patch-record"
    assert guide_file.read_bytes() == b"guide-record"
    assert historical_asset.read_bytes() == PNG_SIGNATURE + b"historical"


@pytest.mark.parametrize(
    "manifest_text",
    [
        "{broken",
        '{"schema_version":true,"entries":{}}',
        '{"schema_version":1,"entries":{"heroes:18":{"kind":"heroes","entity_id":18,"internal_name":"sven","content_sha256":"../escape","source_patch":"7.41"}}}',
        '{"schema_version":1,"entries":{},"extra":1}',
        '{"schema_version":1,"entries":{},"bad":NaN}',
    ],
)
def test_invalid_manifest_fails_before_download_and_preserves_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manifest_text: str,
) -> None:
    data_root = tmp_path / "data"
    _install_store(monkeypatch, data_root, repository=_repository())
    images = data_root / "images"
    images.mkdir(parents=True)
    path = images / "manifest.json"
    original = manifest_text.encode()
    path.write_bytes(original)
    client = FakeImageClient()

    with pytest.raises(ImageRefreshError) as raised:
        refresh_images(data_root=data_root, client=client)

    assert raised.value.reason == "invalid_manifest"
    assert path.read_bytes() == original
    assert client.calls == []


def test_catalog_missing_fails_before_client_is_used(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    _install_store(monkeypatch, data_root)
    client = FakeImageClient()

    with pytest.raises(ImageRefreshError) as raised:
        refresh_images(data_root=data_root, client=client)

    assert raised.value.reason == "catalog_missing"
    assert client.calls == []


def test_catalog_is_loaded_once_and_used_even_if_pointer_changes_during_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    store = _install_store(monkeypatch, data_root, repository=_repository(patch="7.41f"))
    started = threading.Event()
    release = threading.Event()

    class BlockingClient(FakeImageClient):
        def fetch_png(self, kind: str, internal_name: str) -> bytes:
            started.set()
            assert release.wait(5)
            return super().fetch_png(kind, internal_name)

    client = BlockingClient()
    errors: list[BaseException] = []

    def run() -> None:
        try:
            refresh_images(data_root=data_root, workers=1, client=client)
        except BaseException as exc:  # surfaced in the calling test thread
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert started.wait(5)
        store.snapshot = SimpleNamespace(
            revision="d" * 32,
            repository=_repository(patch="7.42"),
        )
    finally:
        release.set()
        thread.join(5)

    assert not thread.is_alive()
    assert errors == []
    assert store.load_calls == 1
    manifest = _read_manifest(data_root)
    assert {entry["source_patch"] for entry in manifest["entries"].values()} == {"7.41f"}


def test_manifest_publish_failure_keeps_previous_manifest_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    _install_store(monkeypatch, data_root, repository=_repository())
    refresh_images(data_root=data_root, client=FakeImageClient())
    path = data_root / "images" / "manifest.json"
    previous = path.read_bytes()
    original_atomic_write = image_refresh._atomic_write

    def fail_manifest_write(target: Path, content: bytes) -> None:
        if target.name == "manifest.json":
            raise OSError("hidden storage details")
        original_atomic_write(target, content)

    monkeypatch.setattr(image_refresh, "_atomic_write", fail_manifest_write)
    monkeypatch.setattr(
        image_refresh,
        "CatalogSnapshotStore",
        lambda _root: FakeStore(
            data_root,
            SimpleNamespace(revision="e" * 32, repository=_repository(patch="7.42")),
        ),
    )

    with pytest.raises(ImageRefreshError) as raised:
        refresh_images(data_root=data_root, client=FakeImageClient())

    assert raised.value.reason == "storage_error"
    assert path.read_bytes() == previous


@pytest.mark.parametrize("workers", [True, 0, -1, 17, 1.5])
def test_worker_limit_is_strict(workers: Any, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        refresh_images(data_root=tmp_path, workers=workers)


def test_download_concurrency_never_exceeds_configured_workers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    _install_store(monkeypatch, data_root, repository=_repository())
    entered = threading.Barrier(2)
    guard = threading.Lock()
    active = 0
    peak = 0
    entry_count = 0

    class MeasuredClient(FakeImageClient):
        def fetch_png(self, kind: str, internal_name: str) -> bytes:
            nonlocal active, peak, entry_count
            with guard:
                active += 1
                peak = max(peak, active)
                entry_count += 1
                current_entry = entry_count
            try:
                if current_entry <= 2:
                    entered.wait(timeout=5)
                return super().fetch_png(kind, internal_name)
            finally:
                with guard:
                    active -= 1

    report = refresh_images(data_root=data_root, workers=2, client=MeasuredClient())
    assert report.downloaded == 3
    assert peak <= 2
