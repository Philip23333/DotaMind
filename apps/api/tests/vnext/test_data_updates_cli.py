from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from redis.exceptions import RedisError

from app.integrations.valve.catalog_repository import CATALOG_DIR
from app.vnext.data_updates import cli
from app.vnext.data_updates.catalog_store import CatalogSnapshotStore
from app.vnext.hero_guides.cache import (
    GuideCacheEntry,
    GuideCacheSnapshot,
    HeroGuideCacheDataError,
    HeroGuideCacheUnavailableError,
    RedisHeroGuideCache,
)
from app.vnext.hero_guides.file_cache import (
    FileHeroGuideCache,
    GuideMigrationConflictError,
)
from app.vnext.hero_guides.migration import (
    GuideMigrationReport,
    GuideMigrationVerificationError,
)

_NOW = datetime(2026, 9, 30, 3, 0, tzinfo=UTC)
_CATALOG_FILES = (
    "manifest.json",
    "dota2_heroes.json",
    "dota2_abilities.json",
    "dota2_items.json",
    "sync_audit.json",
)


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.hgetall_calls: list[str] = []
        self.hset_calls: list[tuple[str, dict[str, str]]] = []
        self.delete_calls: list[tuple[Any, ...]] = []
        self.expire_calls: list[tuple[Any, ...]] = []
        self.ping_calls = 0
        self.close_calls = 0
        self.ping_error: BaseException | None = None

    async def ping(self) -> bool:
        self.ping_calls += 1
        if self.ping_error is not None:
            raise self.ping_error
        return True

    async def hgetall(self, key: str) -> dict[str, str]:
        self.hgetall_calls.append(key)
        return dict(self.hashes.get(key, {}))

    async def hset(self, key: str, *, mapping: dict[str, str]) -> int:
        self.hset_calls.append((key, mapping))
        self.hashes.setdefault(key, {}).update(mapping)
        return 1

    async def delete(self, *keys: Any) -> int:
        self.delete_calls.append(keys)
        return 0

    async def expire(self, *args: Any) -> bool:
        self.expire_calls.append(args)
        return False

    async def aclose(self) -> None:
        self.close_calls += 1


def _invoke(
    argv: list[str],
    *,
    environ: dict[str, str] | None = None,
    refresh_lock_path: Path,
) -> tuple[int, dict[str, Any] | None, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    code = cli.main(
        argv,
        environ={} if environ is None else environ,
        stdout=stdout,
        stderr=stderr,
        refresh_lock_path=refresh_lock_path,
    )
    raw = stdout.getvalue()
    parsed = json.loads(raw) if raw.strip().startswith("{") else None
    if parsed is not None:
        assert raw.count("\n") == 1
    return code, parsed, raw, stderr.getvalue()


def _catalog_args(data_dir: Path, source_dir: Path | None = None) -> list[str]:
    args = ["init-catalog", "--data-dir", str(data_dir)]
    if source_dir is not None:
        args.extend(["--source-dir", str(source_dir)])
    return args


def _initialize(data_dir: Path, refresh_lock_path: Path) -> dict[str, Any]:
    code, payload, _raw, _stderr = _invoke(
        _catalog_args(data_dir), refresh_lock_path=refresh_lock_path
    )
    assert code == 0
    assert payload is not None
    return payload


def _seed_pub_entry(redis_client: FakeRedis, hero_id: int) -> None:
    snapshot = GuideCacheSnapshot(
        sample_type="pub",
        hero_id=hero_id,
        position=1,
        retrieved_at=_NOW,
        content_type="application/json",
        raw_body=b"[]",
        source_rows=[],
        pub_guides=[],
    )
    entry = GuideCacheEntry(snapshot=snapshot, last_attempt_at=_NOW, last_error=None)
    redis_client.hashes[RedisHeroGuideCache._pub_key(hero_id, 1)] = {
        "snapshot": snapshot.model_dump_json(),
        "last_attempt_at": _NOW.isoformat(),
        "last_error": "",
    }
    assert entry.snapshot == snapshot


@pytest.mark.parametrize(
    ("argv", "environ", "reason"),
    [
        (["init-catalog"], {}, "missing_data_dir"),
        (["init-catalog", "--data-dir", ""], {}, "invalid_data_dir"),
        (["init-catalog"], {"DOTAMIND_DATA_DIR": ""}, "invalid_data_dir"),
        (["init-catalog"], {"DOTAMIND_DATA_DIR": "relative/data"}, "invalid_data_dir"),
    ],
)
def test_data_directory_configuration_is_required_and_absolute(
    argv: list[str],
    environ: dict[str, str],
    reason: str,
    tmp_path: Path,
) -> None:
    code, payload, _raw, _stderr = _invoke(
        argv,
        environ=environ,
        refresh_lock_path=tmp_path / "refresh.lock",
    )

    assert code == 2
    assert payload == {"status": "failed", "operation": "init-catalog", "reason": reason}
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("argv", "environ", "reason"),
    [
        (["migrate-guides"], {"DOTAMIND_REDIS_URL": "redis://fake"}, "missing_data_dir"),
        (
            ["migrate-guides", "--data-dir", "relative/data"],
            {"DOTAMIND_REDIS_URL": "redis://fake"},
            "invalid_data_dir",
        ),
    ],
)
def test_migration_requires_a_valid_data_directory_before_redis(
    argv: list[str],
    environ: dict[str, str],
    reason: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_calls: list[str] = []
    monkeypatch.setattr(
        cli, "from_url", lambda *_args, **_kwargs: redis_calls.append("redis")
    )

    code, payload, _raw, _stderr = _invoke(
        argv,
        environ=environ,
        refresh_lock_path=tmp_path / "refresh.lock",
    )

    assert code == 2
    assert payload == {
        "status": "failed",
        "operation": "migrate-guides",
        "reason": reason,
    }
    assert redis_calls == []
    assert list(tmp_path.iterdir()) == []


def test_init_catalog_parameter_takes_precedence_over_environment(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "configured-data"

    code, payload, _raw, _stderr = _invoke(
        ["--data-dir", str(data_dir), "init-catalog"],
        environ={"DOTAMIND_DATA_DIR": "relative/ignored"},
        refresh_lock_path=tmp_path / "refresh.lock",
    )

    assert code == 0
    assert payload is not None and payload["status"] == "success"
    assert (data_dir / "catalog" / "current.json").is_file()


def test_init_catalog_publishes_bundled_five_files_and_reports_real_patch(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "persistent-data"
    source_bytes = {name: (CATALOG_DIR / name).read_bytes() for name in _CATALOG_FILES}

    code, payload, _raw, _stderr = _invoke(
        _catalog_args(data_dir), refresh_lock_path=tmp_path / "refresh.lock"
    )

    assert code == 0
    assert payload is not None
    assert payload["status"] == "success"
    assert payload["operation"] == "init-catalog"
    current = CatalogSnapshotStore(data_dir).load_current()
    assert current is not None
    assert payload["revision"] == current.revision
    assert payload["patch"] == current.repository.manifest.patch
    assert {path.name for path in current.directory.iterdir()} == set(_CATALOG_FILES)
    published_bytes = {
        name: (current.directory / name).read_bytes() for name in _CATALOG_FILES
    }
    bundled_bytes = {name: (CATALOG_DIR / name).read_bytes() for name in _CATALOG_FILES}
    assert published_bytes == source_bytes
    assert bundled_bytes == source_bytes


def test_init_catalog_second_run_skips_without_reading_source_or_revision_change(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "persistent-data"
    refresh_lock = tmp_path / "refresh.lock"
    first = _initialize(data_dir, refresh_lock)

    code, second, _raw, _stderr = _invoke(
        _catalog_args(data_dir, tmp_path / "source-that-does-not-exist"),
        refresh_lock_path=refresh_lock,
    )

    assert code == 0
    assert second == {
        "status": "skipped",
        "operation": "init-catalog",
        "reason": "already_initialized",
        "revision": first["revision"],
        "patch": first["patch"],
    }


def test_corrupt_current_pointer_is_not_overwritten(tmp_path: Path) -> None:
    data_dir = tmp_path / "persistent-data"
    pointer = data_dir / "catalog" / "current.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_bytes(b"{corrupt")

    code, payload, _raw, _stderr = _invoke(
        _catalog_args(data_dir), refresh_lock_path=tmp_path / "refresh.lock"
    )

    assert code == 1
    assert payload == {
        "status": "failed",
        "operation": "init-catalog",
        "reason": "invalid_pointer",
    }
    assert pointer.read_bytes() == b"{corrupt"
    snapshots = data_dir / "catalog" / "snapshots"
    assert not list(snapshots.glob("*")) if snapshots.exists() else True


def test_invalid_catalog_source_does_not_publish_a_pointer(tmp_path: Path) -> None:
    data_dir = tmp_path / "persistent-data"
    source = tmp_path / "incomplete-source"
    source.mkdir()
    (source / _CATALOG_FILES[0]).write_bytes(b"{}")

    code, payload, _raw, _stderr = _invoke(
        _catalog_args(data_dir, source), refresh_lock_path=tmp_path / "refresh.lock"
    )

    assert code == 1
    assert payload is not None and payload["reason"] == "invalid_snapshot"
    assert not (data_dir / "catalog" / "current.json").exists()


def test_data_lock_busy_skips_without_catalog_publication(tmp_path: Path) -> None:
    data_dir = tmp_path / "persistent-data"
    data_dir.mkdir()
    held_fd = cli._try_acquire_lock(data_dir / ".update.lock")
    assert held_fd is not None
    try:
        code, payload, _raw, _stderr = _invoke(
            _catalog_args(data_dir), refresh_lock_path=tmp_path / "refresh.lock"
        )
    finally:
        cli._release_lock(held_fd)

    assert code == 3
    assert payload == {"status": "skipped", "reason": "already_running"}
    assert not (data_dir / "catalog" / "current.json").exists()


def test_data_lock_busy_skips_migration_before_opening_redis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    refresh_lock = tmp_path / "refresh.lock"
    _initialize(data_dir, refresh_lock)
    pointer_before = (data_dir / "catalog" / "current.json").read_bytes()
    held_fd = cli._try_acquire_lock(data_dir / ".update.lock")
    assert held_fd is not None
    redis_calls: list[str] = []
    monkeypatch.setattr(
        cli, "from_url", lambda *_args, **_kwargs: redis_calls.append("redis")
    )
    try:
        code, payload, _raw, _stderr = _invoke(
            ["migrate-guides", "--data-dir", str(data_dir)],
            environ={"DOTAMIND_REDIS_URL": "redis://fake"},
            refresh_lock_path=refresh_lock,
        )
    finally:
        cli._release_lock(held_fd)

    assert code == 3
    assert payload == {"status": "skipped", "reason": "already_running"}
    assert redis_calls == []
    assert (data_dir / "catalog" / "current.json").read_bytes() == pointer_before


def test_help_has_no_data_or_redis_side_effects(tmp_path: Path) -> None:
    stdout = StringIO()
    stderr = StringIO()

    code = cli.main(
        ["--help"],
        environ={},
        stdout=stdout,
        stderr=stderr,
        refresh_lock_path=tmp_path / "refresh.lock",
    )

    assert code == 0
    assert "init-catalog" in stdout.getvalue()
    assert "migrate-guides" in stdout.getvalue()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("command", ["init-catalog", "migrate-guides"])
def test_subcommand_help_has_no_side_effects(command: str, tmp_path: Path) -> None:
    stdout = StringIO()
    stderr = StringIO()

    code = cli.main(
        [command, "--help"],
        environ={},
        stdout=stdout,
        stderr=stderr,
        refresh_lock_path=tmp_path / "refresh.lock",
    )

    assert code == 0
    assert "usage:" in stdout.getvalue().lower()
    assert not list(tmp_path.iterdir())


def test_migrate_requires_catalog_before_creating_redis_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    data_dir.mkdir()
    calls: list[str] = []
    monkeypatch.setattr(cli, "from_url", lambda *_args, **_kwargs: calls.append("redis"))

    code, payload, _raw, _stderr = _invoke(
        ["migrate-guides", "--data-dir", str(data_dir)],
        environ={"DOTAMIND_REDIS_URL": "redis://fake"},
        refresh_lock_path=tmp_path / "refresh.lock",
    )

    assert code == 1
    assert payload == {
        "status": "failed",
        "operation": "migrate-guides",
        "reason": "catalog_missing",
    }
    assert calls == []


def test_corrupt_catalog_pointer_prevents_redis_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    pointer = data_dir / "catalog" / "current.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text("{}", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(cli, "from_url", lambda *_args, **_kwargs: calls.append("redis"))

    code, payload, _raw, _stderr = _invoke(
        ["migrate-guides", "--data-dir", str(data_dir)],
        environ={"DOTAMIND_REDIS_URL": "redis://fake"},
        refresh_lock_path=tmp_path / "refresh.lock",
    )

    assert code == 1
    assert payload is not None and payload["reason"] == "invalid_pointer"
    assert calls == []


def test_redis_url_is_required_before_any_lock_or_client_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    calls: list[str] = []
    monkeypatch.setattr(cli, "from_url", lambda *_args, **_kwargs: calls.append("redis"))

    code, payload, _raw, _stderr = _invoke(
        ["migrate-guides", "--data-dir", str(data_dir)],
        environ={},
        refresh_lock_path=tmp_path / "refresh.lock",
    )

    assert code == 2
    assert payload is not None and payload["reason"] == "missing_redis_url"
    assert calls == []
    assert not data_dir.exists()


def test_migration_uses_catalog_snapshot_heroes_and_existing_importer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    old_lock_path = tmp_path / "old-refresh.lock"
    old_lock_path.parent.mkdir(exist_ok=True)
    redis_client = FakeRedis()
    events: list[Any] = []

    class FakeRepository:
        def list_heroes(self) -> list[SimpleNamespace]:
            events.append("list_heroes")
            return [SimpleNamespace(hero_id=901), SimpleNamespace(hero_id=42)]

    class FakeStore:
        def __init__(self, root: Path) -> None:
            assert root == data_dir
            events.append("store")

        def load_current(self) -> SimpleNamespace:
            events.append("load_catalog")
            return SimpleNamespace(repository=FakeRepository())

    monkeypatch.setattr(cli, "CatalogSnapshotStore", FakeStore)

    def fake_from_url(url: str, *, decode_responses: bool) -> FakeRedis:
        assert url == "redis://fake"
        assert decode_responses is True
        assert cli._try_acquire_lock(data_dir / ".update.lock") is None
        assert cli._try_acquire_lock(old_lock_path) is None
        events.append("redis_create")
        return redis_client

    monkeypatch.setattr(cli, "from_url", fake_from_url)

    async def fake_migrate(
        *, source: Any, target: Any, hero_ids: list[int]
    ) -> GuideMigrationReport:
        assert isinstance(source, RedisHeroGuideCache)
        assert isinstance(target, FileHeroGuideCache)
        events.append(("migrate", hero_ids))
        return GuideMigrationReport(12, 8, 3, 1)

    monkeypatch.setattr(cli, "migrate_redis_guides", fake_migrate)

    code, payload, _raw, _stderr = _invoke(
        ["migrate-guides", "--data-dir", str(data_dir)],
        environ={"DOTAMIND_REDIS_URL": "redis://fake"},
        refresh_lock_path=old_lock_path,
    )

    assert code == 0
    assert payload == {
        "status": "success",
        "operation": "migrate-guides",
        "partitions_checked": 12,
        "missing": 8,
        "imported": 3,
        "already_present": 1,
    }
    assert events.index("load_catalog") < events.index("redis_create")
    assert ("migrate", [901, 42]) in events
    assert redis_client.ping_calls == 1
    assert redis_client.close_calls == 1
    data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
    refresh_lock_fd = cli._try_acquire_lock(old_lock_path)
    assert data_lock is not None and refresh_lock_fd is not None
    cli._release_lock(refresh_lock_fd)
    cli._release_lock(data_lock)


def test_migration_imports_and_readback_skips_identical_guide_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    refresh_lock = tmp_path / "refresh.lock"
    _initialize(data_dir, refresh_lock)
    catalog = CatalogSnapshotStore(data_dir).load_current()
    assert catalog is not None
    hero_id = catalog.repository.list_heroes()[0].hero_id
    redis_client = FakeRedis()
    _seed_pub_entry(redis_client, hero_id)

    def fake_from_url(_url: str, *, decode_responses: bool) -> FakeRedis:
        assert decode_responses is True
        return redis_client

    monkeypatch.setattr(cli, "from_url", fake_from_url)
    args = ["migrate-guides", "--data-dir", str(data_dir)]
    environ = {"DOTAMIND_REDIS_URL": "redis://fake"}
    first_code, first, _first_raw, _ = _invoke(
        args, environ=environ, refresh_lock_path=refresh_lock
    )
    second_code, second, _second_raw, _ = _invoke(
        args, environ=environ, refresh_lock_path=refresh_lock
    )

    total = len(catalog.repository.list_heroes()) * 6
    assert first_code == second_code == 0
    assert first is not None and first["partitions_checked"] == total
    assert first["imported"] == 1
    assert first["already_present"] == 0
    assert second is not None and second["partitions_checked"] == total
    assert second["imported"] == 0
    assert second["already_present"] == 1
    cached = asyncio.run(FileHeroGuideCache(data_dir).get_pub(hero_id=hero_id, position=1))
    assert cached.snapshot is not None and cached.snapshot.raw_body == b"[]"
    assert redis_client.hgetall_calls
    assert redis_client.hset_calls == []
    assert redis_client.delete_calls == []
    assert redis_client.expire_calls == []
    assert redis_client.close_calls == 2


def test_refresh_lock_busy_skips_without_accessing_redis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    refresh_lock = tmp_path / "refresh.lock"
    _initialize(data_dir, refresh_lock)
    held_fd = cli._try_acquire_lock(refresh_lock)
    assert held_fd is not None
    redis_calls: list[str] = []
    monkeypatch.setattr(cli, "from_url", lambda *_args, **_kwargs: redis_calls.append("redis"))
    try:
        code, payload, _raw, _stderr = _invoke(
            ["migrate-guides", "--data-dir", str(data_dir)],
            environ={"DOTAMIND_REDIS_URL": "redis://fake"},
            refresh_lock_path=refresh_lock,
        )
    finally:
        cli._release_lock(held_fd)

    assert code == 3
    assert payload == {"status": "skipped", "reason": "already_running"}
    assert redis_calls == []
    data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
    assert data_lock is not None
    cli._release_lock(data_lock)


def test_second_lock_open_failure_releases_data_lock_before_returning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    _initialize(data_dir, tmp_path / "refresh.lock")
    redis_calls: list[str] = []
    monkeypatch.setattr(cli, "from_url", lambda *_args, **_kwargs: redis_calls.append("redis"))

    code, payload, _raw, _stderr = _invoke(
        ["migrate-guides", "--data-dir", str(data_dir)],
        environ={"DOTAMIND_REDIS_URL": "redis://fake"},
        refresh_lock_path=tmp_path / "missing-parent" / "refresh.lock",
    )

    assert code == 1
    assert payload is not None and payload["reason"] == "storage_error"
    assert redis_calls == []
    data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
    assert data_lock is not None
    cli._release_lock(data_lock)


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (GuideMigrationConflictError(), "migration_conflict"),
        (GuideMigrationVerificationError(), "migration_verification_failed"),
        (HeroGuideCacheDataError(), "cache_invalid_data"),
        (HeroGuideCacheUnavailableError(), "cache_unavailable"),
        (RedisError("redis://user:secret@host"), "redis_unavailable"),
        (RuntimeError("redis://user:secret@host"), "operation_failed"),
    ],
)
def test_migration_failures_have_fixed_reasons_and_close_redis(
    error: Exception,
    reason: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    old_lock = tmp_path / "refresh.lock"
    _initialize(data_dir, old_lock)
    redis_client = FakeRedis()
    monkeypatch.setattr(
        cli,
        "from_url",
        lambda _url, *, decode_responses: redis_client,
    )

    async def fail_migration(**_kwargs: Any) -> GuideMigrationReport:
        raise error

    monkeypatch.setattr(cli, "migrate_redis_guides", fail_migration)
    code, payload, raw, _stderr = _invoke(
        ["migrate-guides", "--data-dir", str(data_dir)],
        environ={"DOTAMIND_REDIS_URL": "redis://user:secret@host"},
        refresh_lock_path=old_lock,
    )

    assert code == 1
    assert payload is not None and payload["reason"] == reason
    assert "secret" not in raw and "redis://" not in raw
    assert redis_client.close_calls == 1
    data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
    assert data_lock is not None
    cli._release_lock(data_lock)


def test_redis_ping_failure_closes_client_without_exposing_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    refresh_lock = tmp_path / "refresh.lock"
    _initialize(data_dir, refresh_lock)
    redis_client = FakeRedis()
    redis_client.ping_error = RedisError("redis://user:secret@host")
    monkeypatch.setattr(cli, "from_url", lambda *_args, **_kwargs: redis_client)

    code, payload, raw, _stderr = _invoke(
        ["migrate-guides", "--data-dir", str(data_dir)],
        environ={"DOTAMIND_REDIS_URL": "redis://user:secret@host"},
        refresh_lock_path=refresh_lock,
    )

    assert code == 1
    assert payload is not None and payload["reason"] == "redis_unavailable"
    assert "secret" not in raw and "redis://" not in raw
    assert redis_client.close_calls == 1


def test_cancellation_closes_redis_and_releases_both_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    refresh_lock = tmp_path / "refresh.lock"
    _initialize(data_dir, refresh_lock)
    redis_client = FakeRedis()
    monkeypatch.setattr(cli, "from_url", lambda *_args, **_kwargs: redis_client)

    async def cancel_migration(**_kwargs: Any) -> GuideMigrationReport:
        raise asyncio.CancelledError

    monkeypatch.setattr(cli, "migrate_redis_guides", cancel_migration)
    code, payload, _raw, _stderr = _invoke(
        ["migrate-guides", "--data-dir", str(data_dir)],
        environ={"DOTAMIND_REDIS_URL": "redis://fake"},
        refresh_lock_path=refresh_lock,
    )

    assert code == 130
    assert payload == {"status": "cancelled"}
    assert redis_client.close_calls == 1
    data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
    refresh_lock_fd = cli._try_acquire_lock(refresh_lock)
    assert data_lock is not None and refresh_lock_fd is not None
    cli._release_lock(refresh_lock_fd)
    cli._release_lock(data_lock)


def test_importing_main_module_does_not_execute_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    monkeypatch.setattr(cli, "main", lambda: pytest.fail("CLI must not run on import"))
    assert importlib.import_module("app.vnext.data_updates.__main__") is not None
