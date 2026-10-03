from __future__ import annotations

import asyncio
import json
import os
import signal
import threading
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from redis.exceptions import RedisError

from app.integrations.valve.catalog_repository import CATALOG_DIR
from app.vnext.data_updates import cli
from app.vnext.data_updates.catalog_refresh import CatalogRefreshReport
from app.vnext.data_updates.catalog_store import CatalogSnapshotStore, CatalogStoreError
from app.vnext.data_updates.image_refresh import (
    ImageRefreshError,
    ImageRefreshFailure,
    ImageRefreshReport,
)
from app.vnext.data_updates.patch_refresh import PatchRefreshError, PatchRefreshReport
from app.vnext.data_updates.refresh_all import (
    RefreshAllModuleResult,
    RefreshAllReport,
)
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
from app.vnext.providers.d2pt import D2PTResponse, D2PTTimeoutError

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
    refresh_clock: Any = None,
    refresh_sleep: Any = None,
    refresh_all_clock: Any = None,
) -> tuple[int, dict[str, Any] | None, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    code = cli.main(
        argv,
        environ={} if environ is None else environ,
        stdout=stdout,
        stderr=stderr,
        refresh_clock=refresh_clock,
        refresh_sleep=refresh_sleep,
        refresh_all_clock=refresh_all_clock,
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


def _refresh_args(data_dir: Path) -> list[str]:
    return ["refresh-guides", "--data-dir", str(data_dir)]


def _catalog_refresh_args(data_dir: Path, *options: str) -> list[str]:
    return ["refresh-catalog", "--data-dir", str(data_dir), *options]


def _patch_refresh_args(data_dir: Path, *options: str) -> list[str]:
    return ["refresh-patches", "--data-dir", str(data_dir), *options]


def _image_refresh_args(data_dir: Path, *options: str) -> list[str]:
    return ["refresh-images", "--data-dir", str(data_dir), *options]


def _response(data: list[dict[str, Any]]) -> D2PTResponse:
    raw_body = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return D2PTResponse(raw_body, data, _NOW, "application/json")


class FakeD2PTClient:
    def __init__(
        self,
        *,
        outcomes: dict[tuple[object, ...], object] | None = None,
        heroes: tuple[int, ...] = (18,),
    ) -> None:
        self.outcomes = {} if outcomes is None else dict(outcomes)
        self.heroes = heroes
        self.calls: list[tuple[object, ...]] = []

    def heroes_list(self) -> D2PTResponse:
        return self._invoke(("heroes_list",), [{"hero_id": hero} for hero in self.heroes])

    def pub_builds(self, hero_id: int, position: int) -> D2PTResponse:
        return self._invoke(("pub_builds", hero_id, position), [])

    def pro_builds(self, hero_id: int) -> D2PTResponse:
        return self._invoke(("pro_builds", hero_id), [])

    def _invoke(
        self,
        key: tuple[object, ...],
        empty_data: list[dict[str, Any]],
    ) -> D2PTResponse:
        self.calls.append(key)
        outcome = self.outcomes.get(key, _response(empty_data))
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, D2PTResponse)
        return outcome


async def _no_sleep(_delay: float) -> None:
    return None


def _initialize(data_dir: Path) -> dict[str, Any]:
    code, payload, _raw, _stderr = _invoke(
        _catalog_args(data_dir)
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
        _catalog_args(data_dir)
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
    first = _initialize(data_dir)

    code, second, _raw, _stderr = _invoke(
        _catalog_args(data_dir, tmp_path / "source-that-does-not-exist"),
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
        _catalog_args(data_dir)
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
        _catalog_args(data_dir, source)
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
            _catalog_args(data_dir)
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
    _initialize(data_dir)
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
    )

    assert code == 0
    assert "init-catalog" in stdout.getvalue()
    assert "migrate-guides" in stdout.getvalue()
    assert "refresh-guides" in stdout.getvalue()
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
    assert data_lock is not None
    cli._release_lock(data_lock)


def test_migration_imports_and_readback_skips_identical_guide_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    _initialize(data_dir)
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
        args, environ=environ
    )
    second_code, second, _second_raw, _ = _invoke(
        args, environ=environ
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
    _initialize(data_dir)
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
    _initialize(data_dir)
    redis_client = FakeRedis()
    redis_client.ping_error = RedisError("redis://user:secret@host")
    monkeypatch.setattr(cli, "from_url", lambda *_args, **_kwargs: redis_client)

    code, payload, raw, _stderr = _invoke(
        ["migrate-guides", "--data-dir", str(data_dir)],
        environ={"DOTAMIND_REDIS_URL": "redis://user:secret@host"},
    )

    assert code == 1
    assert payload is not None and payload["reason"] == "redis_unavailable"
    assert "secret" not in raw and "redis://" not in raw
    assert redis_client.close_calls == 1


def test_cancellation_closes_redis_and_releases_data_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    _initialize(data_dir)
    redis_client = FakeRedis()
    monkeypatch.setattr(cli, "from_url", lambda *_args, **_kwargs: redis_client)

    async def cancel_migration(**_kwargs: Any) -> GuideMigrationReport:
        raise asyncio.CancelledError

    monkeypatch.setattr(cli, "migrate_redis_guides", cancel_migration)
    code, payload, _raw, _stderr = _invoke(
        ["migrate-guides", "--data-dir", str(data_dir)],
        environ={"DOTAMIND_REDIS_URL": "redis://fake"},
    )

    assert code == 130
    assert payload == {"status": "cancelled"}
    assert redis_client.close_calls == 1
    data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
    assert data_lock is not None
    cli._release_lock(data_lock)


def test_importing_main_module_does_not_execute_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    monkeypatch.setattr(cli, "main", lambda: pytest.fail("CLI must not run on import"))
    assert importlib.import_module("app.vnext.data_updates.__main__") is not None


def test_refresh_guides_help_has_no_storage_or_provider_side_effects(
    tmp_path: Path,
) -> None:
    stdout = StringIO()
    stderr = StringIO()

    code = cli.main(
        ["refresh-guides", "--help"],
        environ={},
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert "--data-dir" in stdout.getvalue()
    assert not list(tmp_path.iterdir())


def test_refresh_guides_uses_files_without_redis_and_emits_complete_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    client = FakeD2PTClient()
    monkeypatch.setattr(cli, "D2PTClient", lambda: client)
    monkeypatch.setattr(
        cli, "from_url", lambda *_args, **_kwargs: pytest.fail("Redis is unused")
    )

    code, payload, raw, stderr = _invoke(
        _refresh_args(data_dir),
        environ={},
        refresh_clock=lambda: _NOW,
        refresh_sleep=_no_sleep,
    )

    expected_calls: list[tuple[object, ...]] = [("heroes_list",)]
    expected_calls.extend(("pub_builds", 18, position) for position in range(1, 6))
    expected_calls.append(("pro_builds", 18))
    assert code == 0
    assert stderr == ""
    assert payload is not None
    assert payload["status"] == "success"
    assert payload["operation"] == "refresh-guides"
    assert payload["report"] == {
        "status": "success",
        "started_at": _NOW.isoformat(),
        "finished_at": _NOW.isoformat(),
        "hero_count": 1,
        "request_count": 7,
        "pub_published": 5,
        "pro_published": 1,
        "pub_empty": 5,
        "pro_empty": 1,
        "failures": [],
        "heroes_error": None,
    }
    assert client.calls == expected_calls
    assert raw.count("\n") == 1
    assert (data_dir / "guides" / "pub" / "18" / "1.json").is_file()
    assert (data_dir / "guides" / "pro" / "18.json").is_file()
    assert not (data_dir / "catalog").exists()


def test_refresh_guides_explicit_data_dir_precedes_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit = tmp_path / "explicit-data"
    client = FakeD2PTClient()
    monkeypatch.setattr(cli, "D2PTClient", lambda: client)

    code, payload, _raw, _stderr = _invoke(
        _refresh_args(explicit),
        environ={"DOTAMIND_DATA_DIR": "relative/ignored"},
        refresh_sleep=_no_sleep,
    )

    assert code == 0
    assert payload is not None and payload["operation"] == "refresh-guides"
    assert (explicit / "guides" / "pub" / "18" / "1.json").is_file()
    assert not (tmp_path / "relative" / "ignored").exists()


@pytest.mark.parametrize(
    ("argv", "environ", "reason"),
    [
        (["refresh-guides"], {}, "missing_data_dir"),
        (["refresh-guides", "--data-dir", ""], {}, "invalid_data_dir"),
        (["refresh-guides", "--data-dir", "relative"], {}, "invalid_data_dir"),
    ],
)
def test_refresh_guides_rejects_invalid_data_dir_before_provider_or_locks(
    argv: list[str],
    environ: dict[str, str],
    reason: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli, "D2PTClient", lambda: pytest.fail("D2PT must not start")
    )

    code, payload, _raw, _stderr = _invoke(
        argv,
        environ=environ,
    )

    assert code == 2
    assert payload == {
        "status": "failed",
        "operation": "refresh-guides",
        "reason": reason,
    }
    assert list(tmp_path.iterdir()) == []


def test_refresh_guides_data_lock_busy_does_not_start_d2pt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    data_dir.mkdir()
    held_fd = cli._try_acquire_lock(data_dir / ".update.lock")
    assert held_fd is not None
    monkeypatch.setattr(
        cli, "D2PTClient", lambda: pytest.fail("D2PT must not start")
    )
    try:
        code, payload, _raw, _stderr = _invoke(
            _refresh_args(data_dir),
        )
    finally:
        cli._release_lock(held_fd)

    assert code == 3
    assert payload == {
        "status": "skipped",
        "operation": "refresh-guides",
        "reason": "already_running",
    }


@pytest.mark.parametrize(
    ("outcomes", "expected_status", "expected_code", "expected_reason"),
    [
        ({}, "success", 0, None),
        (
            {("pub_builds", 18, 1): D2PTTimeoutError()},
            "partial",
            4,
            None,
        ),
        ({("heroes_list",): D2PTTimeoutError()}, "failed", 1, None),
    ],
)
def test_refresh_guides_report_status_maps_to_exit_code(
    outcomes: dict[tuple[object, ...], object],
    expected_status: str,
    expected_code: int,
    expected_reason: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    client = FakeD2PTClient(outcomes=outcomes)
    monkeypatch.setattr(cli, "D2PTClient", lambda: client)

    code, payload, raw, _stderr = _invoke(
        _refresh_args(data_dir),
        refresh_clock=lambda: _NOW,
        refresh_sleep=_no_sleep,
    )

    assert code == expected_code
    assert payload is not None
    assert payload["status"] == expected_status
    assert payload["operation"] == "refresh-guides"
    if expected_reason is not None:
        assert payload["reason"] == expected_reason
    else:
        report = payload["report"]
        assert datetime.fromisoformat(report["started_at"]) == _NOW
        assert datetime.fromisoformat(report["finished_at"]) == _NOW
        assert report["request_count"] == len(client.calls)
        assert report["status"] == expected_status
        assert "traceback" not in raw.lower()


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (HeroGuideCacheDataError(), "cache_invalid_data"),
        (HeroGuideCacheUnavailableError(), "cache_unavailable"),
        (RuntimeError("secret provider payload"), "operation_failed"),
    ],
)
def test_refresh_guides_execution_errors_are_safe_and_release_locks(
    error: Exception,
    reason: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    monkeypatch.setattr(cli, "D2PTClient", lambda: FakeD2PTClient())

    async def fail_publish(*_args: Any, **_kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(FileHeroGuideCache, "publish", fail_publish)
    code, payload, raw, _stderr = _invoke(
        _refresh_args(data_dir),
        refresh_sleep=_no_sleep,
    )

    assert code == 1
    assert payload == {
        "status": "failed",
        "operation": "refresh-guides",
        "reason": reason,
    }
    assert "secret provider payload" not in raw
    data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
    assert data_lock is not None
    cli._release_lock(data_lock)


def test_refresh_guides_cancellation_waits_for_file_worker_before_releasing_data_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    write_started = threading.Event()
    release_write = threading.Event()
    command_finished = threading.Event()
    monitor_checked = threading.Event()
    monitor_errors: list[BaseException] = []
    client = FakeD2PTClient()
    monkeypatch.setattr(cli, "D2PTClient", lambda: client)
    original_write = FileHeroGuideCache._write_entry_sync

    def blocked_write(
        cache: FileHeroGuideCache,
        sample_type: str,
        hero_id: int,
        position: int | None,
        entry: GuideCacheEntry,
    ) -> None:
        write_started.set()
        if not release_write.wait(timeout=5):
            raise TimeoutError("test worker was not released")
        original_write(cache, sample_type, hero_id, position, entry)

    monkeypatch.setattr(FileHeroGuideCache, "_write_entry_sync", blocked_write)
    original_main = cli.main

    def monitored_main(*args: Any, **kwargs: Any) -> int:
        try:
            return original_main(*args, **kwargs)
        finally:
            command_finished.set()

    monkeypatch.setattr(cli, "main", monitored_main)

    def cancel_when_write_starts() -> None:
        try:
            assert write_started.wait(timeout=5)
            os.kill(os.getpid(), signal.SIGTERM)
            assert not command_finished.wait(timeout=0.15)
            os.kill(os.getpid(), signal.SIGTERM)
            assert not command_finished.wait(timeout=0.15)
            data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
            assert data_lock is None
            monitor_checked.set()
        except BaseException as exc:
            monitor_errors.append(exc)
        finally:
            release_write.set()

    monitor = threading.Thread(target=cancel_when_write_starts)
    monitor.start()
    code, payload, raw, _stderr = _invoke(
        _refresh_args(data_dir),
        refresh_sleep=_no_sleep,
    )
    monitor.join(timeout=5)

    assert not monitor.is_alive()
    assert monitor_errors == []
    assert monitor_checked.is_set()
    assert command_finished.is_set()
    assert code == 130
    assert payload == {"status": "cancelled", "operation": "refresh-guides"}
    assert raw.count("\n") == 1
    assert client.calls == [("heroes_list",), ("pub_builds", 18, 1)]
    data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
    assert data_lock is not None
    cli._release_lock(data_lock)


def test_refresh_catalog_uses_one_bounded_session_without_redis_or_guide_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    old_guide_lock = tmp_path / "legacy-guide.lock"
    client = object()
    captured_sessions: list[tuple[object, int]] = []
    session_instances: list[object] = []
    refresh_calls: list[dict[str, Any]] = []

    class FakeSession:
        def __init__(self, actual_client: object, *, max_concurrency: int) -> None:
            captured_sessions.append((actual_client, max_concurrency))
            session_instances.append(self)

    monkeypatch.setattr(cli, "ValveDatafeedClient", lambda: client)
    monkeypatch.setattr(cli, "ValveFetchSession", FakeSession)
    def fake_refresh(**kwargs: Any) -> CatalogRefreshReport:
        refresh_calls.append(kwargs)
        return CatalogRefreshReport(
            action="updated",
            reason="missing",
            previous_patch=None,
            target_patch="99.7",
            revision="a" * 32,
        )

    monkeypatch.setattr(cli, "refresh_catalog", fake_refresh)
    monkeypatch.setattr(cli, "from_url", lambda *_args, **_kwargs: pytest.fail("Redis is unused"))

    code, payload, raw, stderr = _invoke(
        _catalog_refresh_args(data_dir, "--workers", "4", "--force"),
        environ={},
    )

    assert code == 0
    assert stderr == ""
    assert payload == {
        "status": "success",
        "operation": "refresh-catalog",
        "report": {
            "action": "updated",
            "reason": "missing",
            "previous_patch": None,
            "target_patch": "99.7",
            "revision": "a" * 32,
        },
    }
    assert raw.count("\n") == 1
    assert captured_sessions == [(client, 4)]
    assert refresh_calls[0]["data_root"] == data_dir
    assert refresh_calls[0]["session"] is session_instances[0]
    assert refresh_calls[0]["workers"] == 4
    assert refresh_calls[0]["force"] is True
    assert not old_guide_lock.exists()
    assert not (data_dir / "catalog").exists()


def test_refresh_catalog_help_has_no_storage_or_provider_side_effects(
    tmp_path: Path,
) -> None:
    stdout = StringIO()
    stderr = StringIO()

    code = cli.main(
        ["refresh-catalog", "--help"],
        environ={},
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert "--workers" in stdout.getvalue()
    assert "--force" in stdout.getvalue()
    assert not list(tmp_path.iterdir())


def test_refresh_catalog_lock_busy_skips_before_client_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    data_dir.mkdir()
    lock_fd = cli._try_acquire_lock(data_dir / ".update.lock")
    assert lock_fd is not None
    client_calls: list[None] = []
    monkeypatch.setattr(cli, "ValveDatafeedClient", lambda: client_calls.append(None))
    try:
        code, payload, _raw, _stderr = _invoke(
            _catalog_refresh_args(data_dir)
        )
    finally:
        cli._release_lock(lock_fd)

    assert code == 3
    assert payload == {
        "status": "skipped",
        "operation": "refresh-catalog",
        "reason": "already_running",
    }
    assert client_calls == []


@pytest.mark.parametrize("workers", ["0", "17", "not-an-integer"])
def test_refresh_catalog_rejects_invalid_workers_before_lock_or_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workers: str,
) -> None:
    data_dir = tmp_path / "persistent-data"
    client_calls: list[None] = []
    monkeypatch.setattr(cli, "ValveDatafeedClient", lambda: client_calls.append(None))

    code, payload, _raw, _stderr = _invoke(
        _catalog_refresh_args(data_dir, "--workers", workers),
    )

    assert code == 2
    assert payload == {
        "status": "failed",
        "operation": "refresh-catalog",
        "reason": "invalid_workers",
    }
    assert not data_dir.exists()
    assert client_calls == []


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (CatalogStoreError("storage_error"), "storage_error"),
        (RuntimeError("secret response payload"), "operation_failed"),
    ],
)
def test_refresh_catalog_failure_is_safe_and_releases_data_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    reason: str,
) -> None:
    data_dir = tmp_path / "persistent-data"
    monkeypatch.setattr(cli, "ValveDatafeedClient", object)
    monkeypatch.setattr(cli, "ValveFetchSession", lambda *_args, **_kwargs: object())

    def fail(**_kwargs: Any) -> CatalogRefreshReport:
        raise error

    monkeypatch.setattr(cli, "refresh_catalog", fail)
    code, payload, raw, _stderr = _invoke(
        _catalog_refresh_args(data_dir)
    )

    assert code == 1
    assert payload == {
        "status": "failed",
        "operation": "refresh-catalog",
        "reason": reason,
    }
    assert "secret response payload" not in raw
    data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
    assert data_lock is not None
    cli._release_lock(data_lock)


def test_refresh_catalog_cancellation_waits_for_worker_before_releasing_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    old_guide_lock = tmp_path / "legacy-guide.lock"
    worker_started = threading.Event()
    release_worker = threading.Event()
    command_finished = threading.Event()
    monitor_checked = threading.Event()
    monitor_errors: list[BaseException] = []
    monkeypatch.setattr(cli, "ValveDatafeedClient", object)
    monkeypatch.setattr(cli, "ValveFetchSession", lambda *_args, **_kwargs: object())

    def blocked_refresh(**_kwargs: Any) -> CatalogRefreshReport:
        worker_started.set()
        if not release_worker.wait(timeout=5):
            raise TimeoutError("test worker was not released")
        return CatalogRefreshReport(
            action="updated",
            reason="missing",
            previous_patch=None,
            target_patch="99.8",
            revision="b" * 32,
        )

    monkeypatch.setattr(cli, "refresh_catalog", blocked_refresh)
    original_main = cli.main

    def monitored_main(*args: Any, **kwargs: Any) -> int:
        try:
            return original_main(*args, **kwargs)
        finally:
            command_finished.set()

    monkeypatch.setattr(cli, "main", monitored_main)

    def cancel_when_worker_starts() -> None:
        try:
            assert worker_started.wait(timeout=5)
            os.kill(os.getpid(), signal.SIGTERM)
            assert not command_finished.wait(timeout=0.15)
            os.kill(os.getpid(), signal.SIGTERM)
            assert not command_finished.wait(timeout=0.15)
            data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
            assert data_lock is None
            monitor_checked.set()
        except BaseException as exc:
            monitor_errors.append(exc)
        finally:
            release_worker.set()

    monitor = threading.Thread(target=cancel_when_worker_starts)
    monitor.start()
    code, payload, raw, _stderr = _invoke(
        _catalog_refresh_args(data_dir),
    )
    monitor.join(timeout=5)

    assert not monitor.is_alive()
    assert monitor_errors == []
    assert monitor_checked.is_set()
    assert command_finished.is_set()
    assert code == 130
    assert payload == {"status": "cancelled", "operation": "refresh-catalog"}
    assert raw.count("\n") == 1
    assert not old_guide_lock.exists()
    data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
    assert data_lock is not None
    cli._release_lock(data_lock)


def test_refresh_patches_uses_one_session_data_lock_and_no_redis_or_guide_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "selected-data"
    environment_dir = tmp_path / "from-environment"
    old_guide_lock = tmp_path / "legacy-guide.lock"
    client = object()
    sessions: list[tuple[object, object]] = []
    refresh_calls: list[dict[str, Any]] = []

    class FakeSession:
        def __init__(self, actual_client: object) -> None:
            sessions.append((actual_client, self))

    monkeypatch.setattr(cli, "ValveDatafeedClient", lambda: client)
    monkeypatch.setattr(cli, "ValveFetchSession", FakeSession)
    monkeypatch.setattr(cli, "from_url", lambda *_args, **_kwargs: pytest.fail("Redis is unused"))

    def fake_refresh(**kwargs: Any) -> PatchRefreshReport:
        refresh_calls.append(kwargs)
        return PatchRefreshReport(
            action="updated",
            reason="missing",
            patch="7.41f",
            content_sha256="a" * 64,
            change_count=3,
        )

    monkeypatch.setattr(cli, "refresh_patches", fake_refresh)
    code, payload, raw, stderr = _invoke(
        _patch_refresh_args(data_dir, "--force"),
        environ={"DOTAMIND_DATA_DIR": str(environment_dir)},
    )

    assert code == 0
    assert stderr == ""
    assert payload == {
        "status": "success",
        "operation": "refresh-patches",
        "report": {
            "action": "updated",
            "reason": "missing",
            "patch": "7.41f",
            "content_sha256": "a" * 64,
            "change_count": 3,
        },
    }
    assert raw.count("\n") == 1
    assert len(sessions) == 1 and sessions[0][0] is client
    assert refresh_calls[0] == {
        "data_root": data_dir,
        "session": sessions[0][1],
        "force": True,
    }
    assert (data_dir / ".update.lock").exists()
    assert not environment_dir.exists()
    assert not old_guide_lock.exists()


def test_refresh_patches_help_has_no_storage_or_provider_side_effects(
    tmp_path: Path,
) -> None:
    stdout = StringIO()
    stderr = StringIO()

    code = cli.main(
        ["refresh-patches", "--help"],
        environ={},
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert "--force" in stdout.getvalue()
    assert not list(tmp_path.iterdir())


def test_refresh_patches_lock_busy_skips_before_client_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    data_dir.mkdir()
    lock_fd = cli._try_acquire_lock(data_dir / ".update.lock")
    assert lock_fd is not None
    client_calls: list[None] = []
    monkeypatch.setattr(cli, "ValveDatafeedClient", lambda: client_calls.append(None))
    try:
        code, payload, _raw, _stderr = _invoke(
            _patch_refresh_args(data_dir),
        )
    finally:
        cli._release_lock(lock_fd)

    assert code == 3
    assert payload == {
        "status": "skipped",
        "operation": "refresh-patches",
        "reason": "already_running",
    }
    assert client_calls == []


def test_refresh_patches_rejects_relative_data_dir_before_client_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_calls: list[None] = []
    monkeypatch.setattr(cli, "ValveDatafeedClient", lambda: client_calls.append(None))

    code, payload, _raw, _stderr = _invoke(
        ["refresh-patches", "--data-dir", "relative-data"],
    )

    assert code == 2
    assert payload == {
        "status": "failed",
        "operation": "refresh-patches",
        "reason": "invalid_data_dir",
    }
    assert client_calls == []
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (PatchRefreshError("storage_error"), "storage_error"),
        (PatchRefreshError("invalid_patch_data"), "invalid_patch_data"),
        (RuntimeError("private provider response"), "operation_failed"),
    ],
)
def test_refresh_patches_failure_is_safe_and_releases_data_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    reason: str,
) -> None:
    data_dir = tmp_path / "persistent-data"
    monkeypatch.setattr(cli, "ValveDatafeedClient", object)
    monkeypatch.setattr(cli, "ValveFetchSession", lambda *_args, **_kwargs: object())

    def fail(**_kwargs: Any) -> PatchRefreshReport:
        raise error

    monkeypatch.setattr(cli, "refresh_patches", fail)
    code, payload, raw, _stderr = _invoke(
        _patch_refresh_args(data_dir)
    )

    assert code == 1
    assert payload == {
        "status": "failed",
        "operation": "refresh-patches",
        "reason": reason,
    }
    assert "private provider response" not in raw
    data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
    assert data_lock is not None
    cli._release_lock(data_lock)


def test_refresh_patches_cancellation_waits_for_worker_before_releasing_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    old_guide_lock = tmp_path / "legacy-guide.lock"
    worker_started = threading.Event()
    release_worker = threading.Event()
    command_finished = threading.Event()
    monitor_checked = threading.Event()
    monitor_errors: list[BaseException] = []
    monkeypatch.setattr(cli, "ValveDatafeedClient", object)
    monkeypatch.setattr(cli, "ValveFetchSession", lambda *_args, **_kwargs: object())

    def blocked_refresh(**_kwargs: Any) -> PatchRefreshReport:
        worker_started.set()
        if not release_worker.wait(timeout=5):
            raise TimeoutError("test worker was not released")
        return PatchRefreshReport(
            action="updated",
            reason="missing",
            patch="7.41f",
            content_sha256="b" * 64,
            change_count=0,
        )

    monkeypatch.setattr(cli, "refresh_patches", blocked_refresh)
    original_main = cli.main

    def monitored_main(*args: Any, **kwargs: Any) -> int:
        try:
            return original_main(*args, **kwargs)
        finally:
            command_finished.set()

    monkeypatch.setattr(cli, "main", monitored_main)

    def cancel_when_worker_starts() -> None:
        try:
            assert worker_started.wait(timeout=5)
            os.kill(os.getpid(), signal.SIGTERM)
            assert not command_finished.wait(timeout=0.15)
            os.kill(os.getpid(), signal.SIGTERM)
            assert not command_finished.wait(timeout=0.15)
            data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
            assert data_lock is None
            monitor_checked.set()
        except BaseException as exc:
            monitor_errors.append(exc)
        finally:
            release_worker.set()

    monitor = threading.Thread(target=cancel_when_worker_starts)
    monitor.start()
    code, payload, raw, _stderr = _invoke(
        _patch_refresh_args(data_dir),
    )
    monitor.join(timeout=5)

    assert not monitor.is_alive()
    assert monitor_errors == []
    assert monitor_checked.is_set()
    assert command_finished.is_set()
    assert code == 130
    assert payload == {"status": "cancelled", "operation": "refresh-patches"}
    assert raw.count("\n") == 1
    assert not old_guide_lock.exists()
    data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
    assert data_lock is not None
    cli._release_lock(data_lock)


def test_refresh_images_uses_data_lock_and_fake_client_without_redis_or_guide_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "selected-data"
    environment_dir = tmp_path / "from-environment"
    old_guide_lock = tmp_path / "legacy-guide.lock"
    client = object()
    client_instances: list[object] = []
    refresh_calls: list[dict[str, Any]] = []

    def make_client() -> object:
        client_instances.append(client)
        return client

    monkeypatch.setattr(cli, "ValveImageClient", make_client)
    monkeypatch.setattr(cli, "from_url", lambda *_args, **_kwargs: pytest.fail("Redis is unused"))

    def fake_refresh(**kwargs: Any) -> ImageRefreshReport:
        refresh_calls.append(kwargs)
        return ImageRefreshReport(
            catalog_revision="a" * 32,
            catalog_patch="7.41f",
            target_count=3,
            downloaded=2,
            skipped=1,
            failures=(),
        )

    monkeypatch.setattr(cli, "refresh_images", fake_refresh)
    code, payload, raw, stderr = _invoke(
        _image_refresh_args(data_dir, "--workers", "4", "--force"),
        environ={"DOTAMIND_DATA_DIR": str(environment_dir)},
    )

    assert code == 0
    assert stderr == ""
    assert payload == {
        "status": "success",
        "operation": "refresh-images",
        "report": {
            "catalog_revision": "a" * 32,
            "catalog_patch": "7.41f",
            "target_count": 3,
            "downloaded": 2,
            "skipped": 1,
            "failures": [],
        },
    }
    assert raw.count("\n") == 1
    assert client_instances == [client]
    assert refresh_calls == [
        {
            "data_root": data_dir,
            "workers": 4,
            "force": True,
            "client": client,
        }
    ]
    assert (data_dir / ".update.lock").exists()
    assert not environment_dir.exists()
    assert not old_guide_lock.exists()


def test_refresh_images_partial_failures_return_exit_code_four(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    monkeypatch.setattr(cli, "ValveImageClient", object)
    monkeypatch.setattr(
        cli,
        "refresh_images",
        lambda **_kwargs: ImageRefreshReport(
            catalog_revision="b" * 32,
            catalog_patch="7.42",
            target_count=2,
            downloaded=1,
            skipped=0,
            failures=(ImageRefreshFailure("heroes", 18, "download_failed"),),
        ),
    )

    code, payload, _raw, _stderr = _invoke(
        _image_refresh_args(data_dir)
    )

    assert code == 4
    assert payload == {
        "status": "partial",
        "operation": "refresh-images",
        "report": {
            "catalog_revision": "b" * 32,
            "catalog_patch": "7.42",
            "target_count": 2,
            "downloaded": 1,
            "skipped": 0,
            "failures": [
                {"kind": "heroes", "entity_id": 18, "error_code": "download_failed"}
            ],
        },
    }


def test_refresh_images_help_has_no_filesystem_or_provider_side_effects(
    tmp_path: Path,
) -> None:
    stdout = StringIO()
    stderr = StringIO()

    code = cli.main(
        ["refresh-images", "--help"],
        environ={},
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert "--workers" in stdout.getvalue()
    assert "--force" in stdout.getvalue()
    assert not list(tmp_path.iterdir())


def test_refresh_images_lock_busy_skips_before_client_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    data_dir.mkdir()
    lock_fd = cli._try_acquire_lock(data_dir / ".update.lock")
    assert lock_fd is not None
    client_calls: list[None] = []
    monkeypatch.setattr(cli, "ValveImageClient", lambda: client_calls.append(None))
    try:
        code, payload, _raw, _stderr = _invoke(
            _image_refresh_args(data_dir)
        )
    finally:
        cli._release_lock(lock_fd)

    assert code == 3
    assert payload == {
        "status": "skipped",
        "operation": "refresh-images",
        "reason": "already_running",
    }
    assert client_calls == []


@pytest.mark.parametrize("workers", ["0", "17", "not-an-int"])
def test_refresh_images_rejects_workers_before_lock_or_download(
    workers: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    client_calls: list[None] = []
    monkeypatch.setattr(cli, "ValveImageClient", lambda: client_calls.append(None))

    code, payload, _raw, _stderr = _invoke(
        _image_refresh_args(data_dir, "--workers", workers),
    )

    assert code == 2
    assert payload == {
        "status": "failed",
        "operation": "refresh-images",
        "reason": "invalid_workers",
    }
    assert not data_dir.exists()
    assert client_calls == []


def test_refresh_images_catalog_missing_is_safe_and_releases_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    monkeypatch.setattr(cli, "ValveImageClient", object)
    monkeypatch.setattr(
        cli,
        "refresh_images",
        lambda **_kwargs: (_ for _ in ()).throw(ImageRefreshError("catalog_missing")),
    )

    code, payload, raw, _stderr = _invoke(
        _image_refresh_args(data_dir)
    )

    assert code == 1
    assert payload == {
        "status": "failed",
        "operation": "refresh-images",
        "reason": "catalog_missing",
    }
    assert "published catalog snapshot" not in raw
    data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
    assert data_lock is not None
    cli._release_lock(data_lock)


def test_refresh_images_cancellation_waits_for_worker_before_releasing_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "persistent-data"
    worker_started = threading.Event()
    release_worker = threading.Event()
    command_finished = threading.Event()
    monitor_checked = threading.Event()
    monitor_errors: list[BaseException] = []
    monkeypatch.setattr(cli, "ValveImageClient", object)

    def blocked_refresh(**_kwargs: Any) -> ImageRefreshReport:
        worker_started.set()
        if not release_worker.wait(timeout=5):
            raise TimeoutError("test worker was not released")
        return ImageRefreshReport("c" * 32, "7.41f", 0, 0, 0, ())

    monkeypatch.setattr(cli, "refresh_images", blocked_refresh)
    original_main = cli.main

    def monitored_main(*args: Any, **kwargs: Any) -> int:
        try:
            return original_main(*args, **kwargs)
        finally:
            command_finished.set()

    monkeypatch.setattr(cli, "main", monitored_main)

    def cancel_when_worker_starts() -> None:
        try:
            assert worker_started.wait(timeout=5)
            os.kill(os.getpid(), signal.SIGTERM)
            assert not command_finished.wait(timeout=0.15)
            data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
            assert data_lock is None
            monitor_checked.set()
        except BaseException as exc:
            monitor_errors.append(exc)
        finally:
            release_worker.set()

    monitor = threading.Thread(target=cancel_when_worker_starts)
    monitor.start()
    code, payload, raw, _stderr = _invoke(
        _image_refresh_args(data_dir)
    )
    monitor.join(timeout=5)

    assert not monitor.is_alive()
    assert monitor_errors == []
    assert monitor_checked.is_set()
    assert command_finished.is_set()
    assert code == 130
    assert payload == {"status": "cancelled", "operation": "refresh-images"}
    assert raw.count("\n") == 1
    data_lock = cli._try_acquire_lock(data_dir / ".update.lock")
    assert data_lock is not None
    cli._release_lock(data_lock)


def _refresh_all_success_report() -> RefreshAllReport:
    return RefreshAllReport(
        status="success",
        started_at=_NOW,
        finished_at=_NOW,
        modules={
            "catalog": RefreshAllModuleResult(
                status="skipped",
                report={"action": "skipped", "reason": "patch_unchanged"},
            ),
            "patches": RefreshAllModuleResult(
                status="success",
                report={"action": "updated", "change_count": 2},
            ),
            "images": RefreshAllModuleResult(
                status="success",
                report={"target_count": 3, "downloaded": 1, "skipped": 2},
            ),
            "guides": RefreshAllModuleResult(
                status="success",
                report={"status": "success", "request_count": 7},
            ),
        },
        exit_code=0,
    )


def test_refresh_all_help_has_no_directory_or_client_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_calls: list[str] = []
    monkeypatch.setattr(cli, "ValveDatafeedClient", lambda: client_calls.append("valve"))
    monkeypatch.setattr(cli, "D2PTClient", lambda: client_calls.append("d2pt"))
    monkeypatch.setattr(cli, "ValveImageClient", lambda: client_calls.append("image"))
    stdout = StringIO()

    code = cli.main(
        ["refresh-all", "--help"],
        environ={},
        stdout=stdout,
        stderr=StringIO(),
    )

    assert code == 0
    assert "--image-workers" in stdout.getvalue()
    assert "--force" in stdout.getvalue()
    assert client_calls == []
    assert not list(tmp_path.iterdir())
    parsed = cli._build_parser(StringIO(), StringIO()).parse_args(["refresh-all"])
    assert parsed.workers == "8"
    assert parsed.image_workers == "8"
    assert parsed.force is False


@pytest.mark.parametrize(
    ("option", "value", "reason"),
    [
        ("--workers", "0", "invalid_workers"),
        ("--workers", "17", "invalid_workers"),
        ("--image-workers", "0", "invalid_image_workers"),
        ("--image-workers", "17", "invalid_image_workers"),
        ("--image-workers", "abc", "invalid_image_workers"),
    ],
)
def test_refresh_all_rejects_invalid_worker_bounds_before_storage(
    tmp_path: Path,
    option: str,
    value: str,
    reason: str,
) -> None:
    data_dir = tmp_path / "data"
    code, payload, _raw, _stderr = _invoke(
        ["refresh-all", "--data-dir", str(data_dir), option, value],
    )

    assert code == 2
    assert payload == {
        "status": "failed",
        "operation": "refresh-all",
        "reason": reason,
    }
    assert not data_dir.exists()


def test_refresh_all_first_lock_busy_starts_no_clients(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    held_fd = cli._try_acquire_lock(data_dir / ".update.lock")
    assert held_fd is not None
    calls: list[str] = []
    monkeypatch.setattr(cli, "ValveDatafeedClient", lambda: calls.append("valve"))
    monkeypatch.setattr(cli, "D2PTClient", lambda: calls.append("d2pt"))
    monkeypatch.setattr(cli, "ValveImageClient", lambda: calls.append("image"))
    try:
        code, payload, _raw, _stderr = _invoke(
            ["refresh-all", "--data-dir", str(data_dir)],
        )
    finally:
        cli._release_lock(held_fd)

    assert code == 3
    assert payload == {
        "status": "skipped",
        "operation": "refresh-all",
        "reason": "already_running",
    }
    assert calls == []


def test_refresh_all_cli_passes_one_bounded_session_under_data_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    valve_client = object()
    image_client = object()
    sessions: list[tuple[object, int, object]] = []
    call_args: list[dict[str, Any]] = []

    class FakeSession:
        def __init__(self, client: object, *, max_concurrency: int) -> None:
            sessions.append((client, max_concurrency, self))

    monkeypatch.setattr(cli, "ValveDatafeedClient", lambda: valve_client)
    monkeypatch.setattr(cli, "ValveFetchSession", FakeSession)
    monkeypatch.setattr(cli, "D2PTClient", lambda: object())
    monkeypatch.setattr(cli, "ValveImageClient", lambda: image_client)
    monkeypatch.setattr(cli, "from_url", lambda *_args, **_kwargs: pytest.fail("Redis is unused"))

    async def fake_refresh_all(**kwargs: Any) -> RefreshAllReport:
        assert cli._try_acquire_lock(data_dir / ".update.lock") is None
        call_args.append(kwargs)
        return _refresh_all_success_report()

    monkeypatch.setattr(cli, "run_refresh_all", fake_refresh_all)
    code, payload, raw, stderr = _invoke(
        [
            "refresh-all",
            "--data-dir",
            str(data_dir),
            "--workers",
            "4",
            "--image-workers",
            "6",
            "--force",
        ],
        refresh_all_clock=lambda: _NOW,
    )

    assert code == 0 and stderr == ""
    assert payload == {
        "status": "success",
        "operation": "refresh-all",
        "started_at": _NOW.isoformat(),
        "finished_at": _NOW.isoformat(),
        "modules": {
            "catalog": {
                "status": "skipped",
                "report": {"action": "skipped", "reason": "patch_unchanged"},
            },
            "patches": {
                "status": "success",
                "report": {"action": "updated", "change_count": 2},
            },
            "images": {
                "status": "success",
                "report": {"target_count": 3, "downloaded": 1, "skipped": 2},
            },
            "guides": {
                "status": "success",
                "report": {"status": "success", "request_count": 7},
            },
        },
    }
    assert raw.count("\n") == 1
    assert len(sessions) == 1
    assert sessions[0][:2] == (valve_client, 4)
    assert len(call_args) == 1
    assert call_args[0]["session"] is sessions[0][2]
    assert call_args[0]["workers"] == 4
    assert call_args[0]["image_workers"] == 6
    assert call_args[0]["force"] is True
    assert call_args[0]["image_client"] is image_client
    assert call_args[0]["data_root"] == data_dir


def test_refresh_all_cli_partial_module_report_returns_exit_code_four(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _refresh_all_success_report()
    partial_report = RefreshAllReport(
        status="partial",
        started_at=report.started_at,
        finished_at=report.finished_at,
        modules={
            **report.modules,
            "images": RefreshAllModuleResult(
                status="partial",
                report={"target_count": 5, "downloaded": 2, "skipped": 2, "failures": 1},
            ),
        },
        exit_code=4,
    )

    async def fake_refresh_all(**_kwargs: Any) -> RefreshAllReport:
        return partial_report

    monkeypatch.setattr(cli, "ValveDatafeedClient", object)
    monkeypatch.setattr(cli, "ValveFetchSession", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(cli, "D2PTClient", object)
    monkeypatch.setattr(cli, "ValveImageClient", object)
    monkeypatch.setattr(cli, "run_refresh_all", fake_refresh_all)

    code, payload, _raw, _stderr = _invoke(
        ["refresh-all", "--data-dir", str(tmp_path / "data")],
    )

    assert code == 4
    assert payload is not None and payload["status"] == "partial"
    assert payload["modules"]["images"] == {
        "status": "partial",
        "report": {"target_count": 5, "downloaded": 2, "skipped": 2, "failures": 1},
    }


def test_refresh_all_cli_sanitizes_unexpected_operation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_refresh_all(**_kwargs: Any) -> RefreshAllReport:
        raise RuntimeError("secret response payload")

    monkeypatch.setattr(cli, "ValveDatafeedClient", object)
    monkeypatch.setattr(cli, "ValveFetchSession", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(cli, "D2PTClient", object)
    monkeypatch.setattr(cli, "ValveImageClient", object)

    # The actual component report path is covered in the orchestration tests; this
    # assertion protects the CLI boundary from provider exception text.
    monkeypatch.setattr(cli, "run_refresh_all", fake_refresh_all)
    code, payload, raw, _stderr = _invoke(
        ["refresh-all", "--data-dir", str(tmp_path / "data")],
    )

    assert code == 1
    assert payload == {
        "status": "failed",
        "operation": "refresh-all",
        "reason": "operation_failed",
    }
    assert "secret response payload" not in raw


def test_refresh_all_cancellation_waits_for_worker_before_releasing_data_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    worker_started = threading.Event()
    release_worker = threading.Event()
    command_finished = threading.Event()
    locks_checked = threading.Event()
    monitor_errors: list[BaseException] = []

    async def fake_refresh_all(**_kwargs: Any) -> RefreshAllReport:
        def blocked_worker() -> None:
            worker_started.set()
            if not release_worker.wait(timeout=5):
                raise TimeoutError("test refresh worker was not released")

        await asyncio.to_thread(blocked_worker)
        return _refresh_all_success_report()

    monkeypatch.setattr(cli, "ValveDatafeedClient", object)
    monkeypatch.setattr(cli, "ValveFetchSession", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(cli, "D2PTClient", object)
    monkeypatch.setattr(cli, "ValveImageClient", object)
    monkeypatch.setattr(cli, "run_refresh_all", fake_refresh_all)
    original_main = cli.main

    def monitored_main(*args: Any, **kwargs: Any) -> int:
        try:
            return original_main(*args, **kwargs)
        finally:
            command_finished.set()

    monkeypatch.setattr(cli, "main", monitored_main)

    def cancel_when_worker_starts() -> None:
        try:
            assert worker_started.wait(timeout=5)
            os.kill(os.getpid(), signal.SIGTERM)
            assert not command_finished.wait(timeout=0.15)
            os.kill(os.getpid(), signal.SIGTERM)
            assert not command_finished.wait(timeout=0.15)
            assert cli._try_acquire_lock(data_dir / ".update.lock") is None
            locks_checked.set()
        except BaseException as exc:
            monitor_errors.append(exc)
        finally:
            release_worker.set()

    monitor = threading.Thread(target=cancel_when_worker_starts)
    monitor.start()
    code, payload, raw, _stderr = _invoke(
        ["refresh-all", "--data-dir", str(data_dir)],
    )
    monitor.join(timeout=5)

    assert not monitor.is_alive()
    assert monitor_errors == []
    assert locks_checked.is_set()
    assert command_finished.is_set()
    assert code == 130
    assert payload == {"status": "cancelled", "operation": "refresh-all"}
    assert raw.count("\n") == 1
    data_fd = cli._try_acquire_lock(data_dir / ".update.lock")
    assert data_fd is not None
    cli._release_lock(data_fd)
