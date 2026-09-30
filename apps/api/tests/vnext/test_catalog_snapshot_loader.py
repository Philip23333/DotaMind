from __future__ import annotations

import asyncio
import json
import logging
import shutil
import threading
from collections.abc import Coroutine
from pathlib import Path
from typing import TypeVar

import pytest

from app.integrations.valve.catalog_repository import CATALOG_DIR
from app.vnext.data_updates.catalog_loader import (
    CatalogNotInitializedError,
    CatalogSnapshotLoader,
)
from app.vnext.data_updates.catalog_store import (
    CatalogSnapshotStore,
    CatalogStoreError,
)

_CATALOG_FILES = (
    "manifest.json",
    "dota2_heroes.json",
    "dota2_abilities.json",
    "dota2_items.json",
    "sync_audit.json",
)
_T = TypeVar("_T")


def _run(awaitable: Coroutine[object, object, _T]) -> _T:
    return asyncio.run(awaitable)


def _copy_catalog_source(destination: Path, *, suffix: str = "") -> Path:
    destination.mkdir(parents=True)
    for filename in _CATALOG_FILES:
        shutil.copyfile(CATALOG_DIR / filename, destination / filename)
    if suffix:
        heroes_path = destination / "dota2_heroes.json"
        heroes = json.loads(heroes_path.read_text(encoding="utf-8"))
        sven = next(hero for hero in heroes if hero["hero_id"] == 18)
        sven["name_en"] += suffix
        heroes_path.write_text(
            json.dumps(heroes, ensure_ascii=False), encoding="utf-8"
        )
    return destination


def _file_bytes(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _published_store(tmp_path: Path) -> tuple[CatalogSnapshotStore, Path]:
    source = _copy_catalog_source(tmp_path / "source")
    store = CatalogSnapshotStore(tmp_path / "data")
    store.publish_from_directory(source)
    return store, source


def _pointer_bytes(revision: str) -> bytes:
    return json.dumps({"schema_version": 1, "revision": revision}).encode("utf-8")


def test_start_loads_current_snapshot_and_current_is_io_free(tmp_path: Path) -> None:
    store, _ = _published_store(tmp_path)
    expected = store.load_current()
    assert expected is not None
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    with pytest.raises(CatalogNotInitializedError):
        loader.current()

    async def scenario() -> None:
        await loader.start()
        current = loader.current()
        assert current.revision == expected.revision
        assert current.repository.get_hero(18) == expected.repository.get_hero(18)
        assert loader._poll_task is not None and not loader._poll_task.done()
        await loader.stop()

    _run(scenario())


@pytest.mark.parametrize("pointer_state", ["missing", "damaged"])
def test_start_failure_has_no_poll_task_and_can_be_retried(
    tmp_path: Path, pointer_state: str
) -> None:
    store = CatalogSnapshotStore(tmp_path / "data")
    if pointer_state == "damaged":
        store._current_pointer.parent.mkdir(parents=True)
        store._current_pointer.write_bytes(b"invalid pointer")
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    async def scenario() -> None:
        expected_error: type[Exception] = (
            CatalogNotInitializedError if pointer_state == "missing" else CatalogStoreError
        )
        with pytest.raises(expected_error):
            await loader.start()
        assert loader._poll_task is None
        with pytest.raises(CatalogNotInitializedError):
            loader.current()

        source = _copy_catalog_source(tmp_path / "repaired")
        store.publish_from_directory(source)
        await loader.start()
        assert loader.current().repository.get_hero(18).name_en == "Sven"
        await loader.stop()

    _run(scenario())


def test_unchanged_revision_only_checks_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    async def scenario() -> None:
        await loader.start()
        checks = 0

        def read_revision() -> str:
            nonlocal checks
            checks += 1
            return loader.current().revision

        def should_not_load() -> None:
            pytest.fail("unchanged revision must not load the five catalog files")

        monkeypatch.setattr(store, "read_current_revision", read_revision)
        monkeypatch.setattr(store, "load_current", should_not_load)
        assert await loader.refresh_once() is False
        assert checks == 1
        await loader.stop()

    _run(scenario())


def test_valid_new_snapshot_switches_and_keeps_old_reference_usable(
    tmp_path: Path,
) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    async def scenario() -> None:
        await loader.start()
        old = loader.current()
        old_name = old.repository.get_hero(18).name_en
        source = _copy_catalog_source(tmp_path / "next", suffix=" Reloaded")
        published = store.publish_from_directory(source)

        assert await loader.refresh_once() is True
        current = loader.current()
        assert current.revision == published.revision
        assert current.repository.get_hero(18).name_en == f"{old_name} Reloaded"
        assert old.repository.get_hero(18).name_en == old_name
        assert await loader.refresh_once() is False
        await loader.stop()

    _run(scenario())


def test_current_does_not_block_while_new_snapshot_is_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    async def scenario() -> None:
        await loader.start()
        old = loader.current()
        source = _copy_catalog_source(tmp_path / "next", suffix=" Slow")
        store.publish_from_directory(source)
        original_load = store.load_current
        entered = threading.Event()
        release = threading.Event()

        def slow_load():
            entered.set()
            if not release.wait(5):
                raise AssertionError("test did not release the blocked catalog load")
            return original_load()

        monkeypatch.setattr(store, "load_current", slow_load)
        refresh = asyncio.create_task(loader.refresh_once())
        assert await asyncio.to_thread(entered.wait, 2)
        assert loader.current() is old
        release.set()
        assert await refresh is True
        await loader.stop()

    _run(scenario())


def test_damaged_snapshot_keeps_old_then_recovers_after_repair(tmp_path: Path) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    async def scenario() -> None:
        await loader.start()
        old = loader.current()
        source = _copy_catalog_source(tmp_path / "next", suffix=" Damaged")
        published = store.publish_from_directory(source)
        heroes_file = published.directory / "dota2_heroes.json"
        valid_bytes = heroes_file.read_bytes()
        heroes_file.write_text("not json", encoding="utf-8")

        with pytest.raises(CatalogStoreError) as raised:
            await loader.refresh_once()
        assert raised.value.reason == "invalid_snapshot"
        assert loader.current() is old

        heroes_file.write_bytes(valid_bytes)
        assert await loader.refresh_once() is True
        assert loader.current().revision == published.revision
        await loader.stop()

    _run(scenario())


@pytest.mark.parametrize("failure", ["missing_pointer", "read_error"])
def test_pointer_disappearance_or_read_failure_keeps_old_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    async def scenario() -> None:
        await loader.start()
        old = loader.current()
        if failure == "missing_pointer":
            store._current_pointer.unlink()
            with pytest.raises(CatalogNotInitializedError):
                await loader.refresh_once()
        else:
            def fail_read() -> str:
                raise CatalogStoreError("storage_error") from OSError(
                    "secret path /private/catalog/current.json"
                )

            monkeypatch.setattr(store, "read_current_revision", fail_read)
            with pytest.raises(CatalogStoreError) as raised:
                await loader.refresh_once()
            assert raised.value.reason == "storage_error"

        assert loader.current() is old
        await loader.stop()

    _run(scenario())


def test_refresh_uses_revision_returned_by_actual_snapshot_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    async def scenario() -> None:
        await loader.start()
        source_b = _copy_catalog_source(tmp_path / "source-b", suffix=" B")
        snapshot_b = store.publish_from_directory(source_b)
        source_c = _copy_catalog_source(tmp_path / "source-c", suffix=" C")
        snapshot_c = store.publish_from_directory(source_c)
        monkeypatch.setattr(store, "read_current_revision", lambda: snapshot_b.revision)

        assert await loader.refresh_once() is True
        current = loader.current()
        assert current.revision == snapshot_c.revision
        assert current.repository.get_hero(18).name_en == "Sven C"
        await loader.stop()

    _run(scenario())


def test_refresh_allows_pointer_rollback_to_an_older_revision(tmp_path: Path) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    async def scenario() -> None:
        await loader.start()
        snapshot_a = loader.current()
        source_b = _copy_catalog_source(tmp_path / "source-b", suffix=" B")
        snapshot_b = store.publish_from_directory(source_b)
        assert await loader.refresh_once() is True
        assert loader.current().revision == snapshot_b.revision

        store._current_pointer.write_bytes(_pointer_bytes(snapshot_a.revision))
        assert await loader.refresh_once() is True
        assert loader.current().revision == snapshot_a.revision
        assert loader.current().repository.get_hero(18).name_en == "Sven"
        await loader.stop()

    _run(scenario())


def test_concurrent_refreshes_are_serialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    async def scenario() -> None:
        await loader.start()
        source = _copy_catalog_source(tmp_path / "next", suffix=" Concurrent")
        store.publish_from_directory(source)
        original_read = store.read_current_revision
        entered = threading.Event()
        release = threading.Event()
        active_reads = 0
        max_active_reads = 0
        load_calls = 0
        original_load = store.load_current

        def blocked_read() -> str | None:
            nonlocal active_reads, max_active_reads
            active_reads += 1
            max_active_reads = max(max_active_reads, active_reads)
            entered.set()
            if not release.wait(5):
                raise AssertionError("test did not release the revision read")
            try:
                return original_read()
            finally:
                active_reads -= 1

        def count_load():
            nonlocal load_calls
            load_calls += 1
            return original_load()

        monkeypatch.setattr(store, "read_current_revision", blocked_read)
        monkeypatch.setattr(store, "load_current", count_load)
        first = asyncio.create_task(loader.refresh_once())
        assert await asyncio.to_thread(entered.wait, 2)
        second = asyncio.create_task(loader.refresh_once())
        await asyncio.sleep(0)
        release.set()
        assert await asyncio.gather(first, second) == [True, False]
        assert max_active_reads == 1
        assert load_calls == 1
        await loader.stop()

    _run(scenario())


def test_repeated_start_creates_only_one_poller_and_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    async def scenario() -> None:
        load_calls = 0
        original_load = store.load_current

        def count_load():
            nonlocal load_calls
            load_calls += 1
            return original_load()

        monkeypatch.setattr(store, "load_current", count_load)
        await loader.start()
        task = loader._poll_task
        await loader.start()
        assert loader._poll_task is task
        assert load_calls == 1
        await loader.stop()

    _run(scenario())


def test_stop_wakes_long_poll_wait_and_is_idempotent(tmp_path: Path) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    async def scenario() -> None:
        await loader.start()
        task = loader._poll_task
        assert task is not None
        await loader.stop()
        await loader.stop()
        assert task.done()
        assert loader._poll_task is None

    _run(scenario())


def test_stop_waits_for_inflight_background_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=0.01)

    async def scenario() -> None:
        await loader.start()
        source = _copy_catalog_source(tmp_path / "next", suffix=" During Stop")
        store.publish_from_directory(source)
        original_load = store.load_current
        entered = threading.Event()
        release = threading.Event()

        def slow_load():
            entered.set()
            if not release.wait(5):
                raise AssertionError("test did not release the background load")
            return original_load()

        monkeypatch.setattr(store, "load_current", slow_load)
        assert await asyncio.to_thread(entered.wait, 2)
        task = asyncio.create_task(loader.stop())
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        await task
        assert loader._poll_task is None
        assert loader.current().repository.get_hero(18).name_en == "Sven During Stop"

    _run(scenario())


def test_stopped_loader_does_not_poll_and_restart_reloads_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=0.01)

    async def scenario() -> None:
        await loader.start()
        original = loader.current()
        await loader.stop()
        source = _copy_catalog_source(tmp_path / "next", suffix=" Restarted")
        store.publish_from_directory(source)
        checks = 0
        original_read = store.read_current_revision

        def count_read() -> str | None:
            nonlocal checks
            checks += 1
            return original_read()

        monkeypatch.setattr(store, "read_current_revision", count_read)
        await asyncio.sleep(0.04)
        assert checks == 0
        assert loader.current() is original

        await loader.start()
        assert loader.current().repository.get_hero(18).name_en == "Sven Restarted"
        assert checks == 0
        await loader.stop()

    _run(scenario())


def test_queries_do_not_write_snapshot_or_source_files(tmp_path: Path) -> None:
    store, source = _published_store(tmp_path)
    source_before = _file_bytes(source)
    data_before = _file_bytes(tmp_path / "data")
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    async def scenario() -> None:
        await loader.start()
        loader.current().repository.get_hero(18)
        assert await loader.refresh_once() is False
        assert _file_bytes(source) == source_before
        assert _file_bytes(tmp_path / "data") == data_before
        await loader.stop()

    _run(scenario())


@pytest.mark.parametrize(
    "interval",
    [True, False, 0, -1, 0.0, -0.1, float("nan"), float("inf"), -float("inf"), "1"],
)
def test_poll_interval_must_be_finite_positive_non_boolean_number(interval: object) -> None:
    with pytest.raises(ValueError):
        CatalogSnapshotLoader(object(), poll_interval_seconds=interval)  # type: ignore[arg-type]


@pytest.mark.parametrize("interval", [0.001, 1, 30.0])
def test_poll_interval_accepts_finite_positive_numbers(interval: float) -> None:
    loader = CatalogSnapshotLoader(object(), poll_interval_seconds=interval)  # type: ignore[arg-type]
    assert loader._poll_interval_seconds == float(interval)


def test_background_logs_only_fixed_reason_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=0.01)
    failures = 0

    async def scenario() -> None:
        await loader.start()

        def fail_read() -> str:
            nonlocal failures
            failures += 1
            raise CatalogStoreError("storage_error") from OSError(
                "secret file contents and /private/data/catalog/current.json"
            )

        monkeypatch.setattr(store, "read_current_revision", fail_read)
        caplog.set_level(logging.WARNING, logger="app.vnext.data_updates.catalog_loader")
        await asyncio.sleep(0.045)
        task = loader._poll_task
        assert task is not None and not task.done()
        assert loader.current().repository.get_hero(18).name_en == "Sven"
        await loader.stop()

    _run(scenario())
    assert failures >= 2
    assert "storage_error" in caplog.text
    assert "secret file contents" not in caplog.text
    assert "/private/data" not in caplog.text


def test_cancelled_full_load_holds_refresh_and_stop_until_worker_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    async def scenario() -> None:
        await loader.start()
        old = loader.current()
        source = _copy_catalog_source(tmp_path / "next", suffix=" Cancelled")
        store.publish_from_directory(source)
        original_load = store.load_current
        entered = threading.Event()
        release = threading.Event()

        def blocked_load():
            entered.set()
            if not release.wait(5):
                raise AssertionError("test did not release the full snapshot load")
            return original_load()

        monkeypatch.setattr(store, "load_current", blocked_load)
        refresh = asyncio.create_task(loader.refresh_once())
        assert await asyncio.to_thread(entered.wait, 2)
        refresh.cancel()
        await asyncio.sleep(0)
        assert not refresh.done()

        stop = asyncio.create_task(loader.stop())
        await loader._stop_event.wait()
        assert not refresh.done()
        assert not stop.done()
        refresh.cancel()
        await asyncio.sleep(0)
        assert not refresh.done()
        assert not stop.done()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await refresh
        assert loader.current() is old
        await stop
        assert loader.current() is old

    _run(scenario())


def test_cancelled_revision_check_waits_before_stop_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    async def scenario() -> None:
        await loader.start()
        old = loader.current()
        entered = threading.Event()
        release = threading.Event()
        load_calls = 0
        original_load = store.load_current

        def blocked_revision() -> str:
            entered.set()
            if not release.wait(5):
                raise AssertionError("test did not release the revision check")
            return old.revision

        def count_load():
            nonlocal load_calls
            load_calls += 1
            return original_load()

        monkeypatch.setattr(store, "read_current_revision", blocked_revision)
        monkeypatch.setattr(store, "load_current", count_load)
        refresh = asyncio.create_task(loader.refresh_once())
        assert await asyncio.to_thread(entered.wait, 2)
        refresh.cancel()
        await asyncio.sleep(0)
        assert not refresh.done()

        stop = asyncio.create_task(loader.stop())
        await loader._stop_event.wait()
        assert not stop.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await refresh
        await stop
        assert load_calls == 0
        assert loader.current() is old

    _run(scenario())


def test_cancelled_start_waits_for_load_and_can_be_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    async def scenario() -> None:
        original_load = store.load_current
        entered = threading.Event()
        release = threading.Event()
        load_calls = 0
        active_workers = 0

        def first_load_blocks():
            nonlocal load_calls, active_workers
            load_calls += 1
            active_workers += 1
            try:
                if load_calls == 1:
                    entered.set()
                    if not release.wait(5):
                        raise AssertionError("test did not release the startup load")
                return original_load()
            finally:
                active_workers -= 1

        monkeypatch.setattr(store, "load_current", first_load_blocks)
        start = asyncio.create_task(loader.start())
        assert await asyncio.to_thread(entered.wait, 2)
        start.cancel()
        await asyncio.sleep(0)
        assert not start.done()
        start.cancel()
        await asyncio.sleep(0)
        assert not start.done()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await start
        assert active_workers == 0
        assert loader._poll_task is None
        with pytest.raises(CatalogNotInitializedError):
            loader.current()

        await loader.start()
        assert load_calls == 2
        assert loader.current().repository.get_hero(18).name_en == "Sven"
        await loader.stop()

    _run(scenario())


def test_cancelled_stop_finishes_background_refresh_before_propagating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=0.005)

    async def scenario() -> None:
        await loader.start()
        source = _copy_catalog_source(tmp_path / "next", suffix=" Stop Cancelled")
        original_load = store.load_current
        entered = threading.Event()
        release = threading.Event()
        active_workers = 0

        def blocked_load():
            nonlocal active_workers
            active_workers += 1
            entered.set()
            try:
                if not release.wait(5):
                    raise AssertionError("test did not release the background load")
                return original_load()
            finally:
                active_workers -= 1

        monkeypatch.setattr(store, "load_current", blocked_load)
        store.publish_from_directory(source)
        assert await asyncio.to_thread(entered.wait, 2)

        stop = asyncio.create_task(loader.stop())
        await loader._stop_event.wait()
        stop.cancel()
        await asyncio.sleep(0)
        assert not stop.done()
        stop.cancel()
        await asyncio.sleep(0)
        assert not stop.done()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await stop
        assert active_workers == 0
        assert loader._poll_task is None
        assert loader.current().repository.get_hero(18).name_en == "Sven Stop Cancelled"

    _run(scenario())


def test_followup_refresh_waits_for_cancelled_read_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _published_store(tmp_path)
    loader = CatalogSnapshotLoader(store, poll_interval_seconds=3600)

    async def scenario() -> None:
        await loader.start()
        old = loader.current()
        source = _copy_catalog_source(tmp_path / "next", suffix=" Serialized")
        store.publish_from_directory(source)
        original_load = store.load_current
        entered = threading.Event()
        release = threading.Event()
        calls = 0
        active_workers = 0
        max_active_workers = 0

        def controlled_load():
            nonlocal calls, active_workers, max_active_workers
            calls += 1
            active_workers += 1
            max_active_workers = max(max_active_workers, active_workers)
            try:
                if calls == 1:
                    entered.set()
                    if not release.wait(5):
                        raise AssertionError("test did not release the first load")
                return original_load()
            finally:
                active_workers -= 1

        monkeypatch.setattr(store, "load_current", controlled_load)
        cancelled_refresh = asyncio.create_task(loader.refresh_once())
        assert await asyncio.to_thread(entered.wait, 2)
        cancelled_refresh.cancel()
        await asyncio.sleep(0)
        assert not cancelled_refresh.done()

        following_refresh = asyncio.create_task(loader.refresh_once())
        await asyncio.sleep(0)
        assert not following_refresh.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await cancelled_refresh
        assert loader.current() is old
        assert await following_refresh is True
        assert calls == 2
        assert max_active_workers == 1
        assert active_workers == 0
        await loader.stop()

    _run(scenario())
