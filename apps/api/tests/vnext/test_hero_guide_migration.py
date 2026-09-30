from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from redis.exceptions import RedisError

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
    GuideMigrationVerificationError,
    migrate_redis_guides,
)

_NOW = datetime(2026, 9, 28, 3, 0, tzinfo=UTC)
_PUB_KEYS = [f"dotamind:vnext:hero-guide:v1:pub:18:{position}" for position in range(1, 6)]
_PRO_KEY = "dotamind:vnext:hero-guide:v1:pro:18"


class RecordingRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.operations: list[tuple[str, str]] = []
        self.fail_hgetall = False

    async def hset(self, key: str, *, mapping: dict[str, str]) -> int:
        self.operations.append(("hset", key))
        target = self.hashes.setdefault(key, {})
        added = sum(field not in target for field in mapping)
        target.update(mapping)
        return added

    async def hgetall(self, key: str) -> dict[str, str]:
        self.operations.append(("hgetall", key))
        if self.fail_hgetall:
            raise RedisError("REDIS_PRIVATE_PAYLOAD")
        return dict(self.hashes.get(key, {}))

    async def delete(self, *keys: str) -> int:
        self.operations.extend(("delete", key) for key in keys)
        return 0

    async def expire(self, key: str, _seconds: int) -> bool:
        self.operations.append(("expire", key))
        return False


def _run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def _pub_snapshot(
    *,
    hero_id: int = 18,
    position: int = 1,
    raw_body: bytes = b"[]",
    source_rows: list[dict[str, Any]] | None = None,
) -> GuideCacheSnapshot:
    return GuideCacheSnapshot(
        sample_type="pub",
        hero_id=hero_id,
        position=position,
        retrieved_at=_NOW,
        content_type="application/json",
        raw_body=raw_body,
        source_rows=[] if source_rows is None else source_rows,
        pub_guides=[],
    )


def _pro_snapshot(
    *,
    hero_id: int = 18,
    raw_body: bytes = b"[]",
    source_rows: list[dict[str, Any]] | None = None,
) -> GuideCacheSnapshot:
    return GuideCacheSnapshot(
        sample_type="pro",
        hero_id=hero_id,
        position=None,
        retrieved_at=_NOW,
        content_type="application/json",
        raw_body=raw_body,
        source_rows=[] if source_rows is None else source_rows,
        pro_examples=[],
    )


async def _seed_migration_state(
    cache: RedisHeroGuideCache,
) -> dict[tuple[str, int, int | None], GuideCacheEntry]:
    expected: dict[tuple[str, int, int | None], GuideCacheEntry] = {}
    pub_success = _pub_snapshot(raw_body=b"pub-18-1", source_rows=[{"winner": 1}])
    await cache.publish(pub_success, attempted_at=_NOW - timedelta(minutes=2))
    expected[("pub", 18, 1)] = await cache.get_pub(hero_id=18, position=1)

    pub_empty = _pub_snapshot(position=3, raw_body=b"[]")
    await cache.publish(pub_empty, attempted_at=_NOW - timedelta(minutes=1))
    expected[("pub", 18, 3)] = await cache.get_pub(hero_id=18, position=3)

    await cache.record_failure(
        sample_type="pub",
        hero_id=18,
        position=2,
        attempted_at=_NOW,
        error_code="timeout",
    )
    expected[("pub", 18, 2)] = await cache.get_pub(hero_id=18, position=2)

    pro_success = _pro_snapshot(raw_body=b"pro-18", source_rows=[{"recent_matches": []}])
    await cache.publish(pro_success, attempted_at=_NOW - timedelta(minutes=1))
    await cache.record_failure(
        sample_type="pro",
        hero_id=18,
        attempted_at=_NOW,
        error_code="http_error",
    )
    expected[("pro", 18, None)] = await cache.get_pro(hero_id=18)

    await cache.record_failure(
        sample_type="pro",
        hero_id=19,
        attempted_at=_NOW,
        error_code="transport_error",
    )
    expected[("pro", 19, None)] = await cache.get_pro(hero_id=19)
    return expected


def test_migration_reads_six_ordered_partitions_per_unique_hero_and_verifies_entries(
    tmp_path: Path,
) -> None:
    redis = RecordingRedis()
    source = RedisHeroGuideCache(redis)
    expected = _run(_seed_migration_state(source))
    redis.operations.clear()
    target = FileHeroGuideCache(tmp_path)

    report = _run(
        migrate_redis_guides(
            source=source,
            target=target,
            hero_ids=[18, 19, 18],
        )
    )

    expected_reads = [
        *(f"dotamind:vnext:hero-guide:v1:pub:18:{position}" for position in range(1, 6)),
        "dotamind:vnext:hero-guide:v1:pro:18",
        *(f"dotamind:vnext:hero-guide:v1:pub:19:{position}" for position in range(1, 6)),
        "dotamind:vnext:hero-guide:v1:pro:19",
    ]
    assert redis.operations == [("hgetall", key) for key in expected_reads]
    assert report.partitions_checked == 12
    assert report.missing == 7
    assert report.imported == 5
    assert report.already_present == 0
    assert report.partitions_checked == report.missing + report.imported + report.already_present
    assert all(operation == "hgetall" for operation, _ in redis.operations)

    for (sample_type, hero_id, position), expected_entry in expected.items():
        if sample_type == "pub":
            actual = _run(target.get_pub(hero_id=hero_id, position=position))
        else:
            actual = _run(target.get_pro(hero_id=hero_id))
        assert actual == expected_entry
    assert not (tmp_path / "guides" / "pub" / "18" / "4.json").exists()
    assert not (tmp_path / "guides" / "pub" / "19").exists()

    redis.operations.clear()
    resumed = _run(
        migrate_redis_guides(
            source=source,
            target=target,
            hero_ids=[18, 19],
        )
    )
    assert resumed.partitions_checked == 12
    assert resumed.missing == 7
    assert resumed.imported == 0
    assert resumed.already_present == 5
    assert resumed.partitions_checked == (
        resumed.missing + resumed.imported + resumed.already_present
    )
    assert all(operation == "hgetall" for operation, _ in redis.operations)


def test_one_hero_reads_exactly_pub_one_through_five_then_pro(tmp_path: Path) -> None:
    redis = RecordingRedis()
    source = RedisHeroGuideCache(redis)
    target = FileHeroGuideCache(tmp_path)

    report = _run(migrate_redis_guides(source=source, target=target, hero_ids=[18]))

    assert report.partitions_checked == report.missing == 6
    assert report.imported == report.already_present == 0
    assert redis.operations == [
        *(('hgetall', key) for key in _PUB_KEYS),
        ("hgetall", _PRO_KEY),
    ]
    assert not (tmp_path / "guides").exists()


@pytest.mark.parametrize(
    "hero_ids",
    [
        [18, True],
        [18, 0],
        [18, -2],
        [18, 1.5],
        [18, "19"],
        "18",
        b"18",
    ],
)
def test_all_hero_ids_are_validated_before_any_io(
    tmp_path: Path,
    hero_ids: object,
) -> None:
    redis = RecordingRedis()
    source = RedisHeroGuideCache(redis)
    target = FileHeroGuideCache(tmp_path)

    with pytest.raises(ValueError):
        _run(migrate_redis_guides(source=source, target=target, hero_ids=hero_ids))  # type: ignore[arg-type]

    assert redis.operations == []
    assert not (tmp_path / "guides").exists()


def test_empty_hero_sequence_performs_no_io(tmp_path: Path) -> None:
    redis = RecordingRedis()
    target = FileHeroGuideCache(tmp_path)
    report = _run(
        migrate_redis_guides(
            source=RedisHeroGuideCache(redis),
            target=target,
            hero_ids=[],
        )
    )
    assert report.partitions_checked == report.missing == 0
    assert report.imported == report.already_present == 0
    assert redis.operations == []
    assert not (tmp_path / "guides").exists()


def test_conflicting_file_target_stops_without_overwriting_or_reporting_success(
    tmp_path: Path,
) -> None:
    redis = RecordingRedis()
    source = RedisHeroGuideCache(redis)
    source_entry = GuideCacheEntry(
        snapshot=_pub_snapshot(raw_body=b"from-redis"),
        last_attempt_at=_NOW,
    )
    _run(source.publish(source_entry.snapshot, attempted_at=source_entry.last_attempt_at))
    target = FileHeroGuideCache(tmp_path)
    target_entry = GuideCacheEntry(
        snapshot=_pub_snapshot(raw_body=b"existing-file"),
        last_attempt_at=_NOW,
    )
    assert _run(
        target.import_entry(sample_type="pub", hero_id=18, position=1, entry=target_entry)
    )
    path = tmp_path / "guides" / "pub" / "18" / "1.json"
    original = path.read_bytes()
    redis.operations.clear()

    with pytest.raises(GuideMigrationConflictError):
        _run(migrate_redis_guides(source=source, target=target, hero_ids=[18]))

    assert redis.operations == [("hgetall", _PUB_KEYS[0])]
    assert path.read_bytes() == original


def test_corrupt_target_stops_import_without_overwrite(tmp_path: Path) -> None:
    redis = RecordingRedis()
    source = RedisHeroGuideCache(redis)
    _run(source.publish(_pub_snapshot(raw_body=b"from-redis"), attempted_at=_NOW))
    redis.operations.clear()
    target = FileHeroGuideCache(tmp_path)
    path = tmp_path / "guides" / "pub" / "18" / "1.json"
    path.parent.mkdir(parents=True)
    path.write_text("damaged", encoding="utf-8")
    original = path.read_bytes()

    with pytest.raises(HeroGuideCacheDataError):
        _run(migrate_redis_guides(source=source, target=target, hero_ids=[18]))

    assert path.read_bytes() == original
    assert redis.operations == [("hgetall", _PUB_KEYS[0])]


def test_source_read_failure_stops_without_a_success_report(tmp_path: Path) -> None:
    redis = RecordingRedis()
    redis.fail_hgetall = True
    target = FileHeroGuideCache(tmp_path)

    with pytest.raises(HeroGuideCacheUnavailableError) as raised:
        _run(
            migrate_redis_guides(
                source=RedisHeroGuideCache(redis),
                target=target,
                hero_ids=[18],
            )
        )

    assert "REDIS_PRIVATE_PAYLOAD" not in str(raised.value)
    assert redis.operations == [("hgetall", _PUB_KEYS[0])]
    assert not (tmp_path / "guides").exists()


def test_target_write_failure_stops_without_a_success_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = RecordingRedis()
    source = RedisHeroGuideCache(redis)
    _run(source.publish(_pub_snapshot(raw_body=b"from-redis"), attempted_at=_NOW))
    redis.operations.clear()
    target = FileHeroGuideCache(tmp_path)

    def fail_replace(*_args: object) -> None:
        raise OSError("injected disk failure")

    monkeypatch.setattr("app.vnext.hero_guides.file_cache.os.replace", fail_replace)
    with pytest.raises(HeroGuideCacheUnavailableError):
        _run(migrate_redis_guides(source=source, target=target, hero_ids=[18]))

    assert redis.operations == [("hgetall", _PUB_KEYS[0])]
    assert not (tmp_path / "guides" / "pub" / "18" / "1.json").exists()


def test_read_back_mismatch_uses_fixed_verification_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = RecordingRedis()
    source = RedisHeroGuideCache(redis)
    _run(source.publish(_pub_snapshot(raw_body=b"from-redis"), attempted_at=_NOW))
    target = FileHeroGuideCache(tmp_path)

    async def wrong_readback(*, hero_id: int, position: int) -> GuideCacheEntry:
        return GuideCacheEntry()

    monkeypatch.setattr(target, "get_pub", wrong_readback)
    with pytest.raises(GuideMigrationVerificationError) as raised:
        _run(migrate_redis_guides(source=source, target=target, hero_ids=[18]))

    assert str(raised.value) == "hero guide migration read-back verification failed"
    assert (tmp_path / "guides" / "pub" / "18" / "1.json").is_file()


def test_empty_cache_entries_are_not_imported_and_redis_is_read_only(tmp_path: Path) -> None:
    redis = RecordingRedis()
    source = RedisHeroGuideCache(redis)
    target = FileHeroGuideCache(tmp_path)

    report = _run(migrate_redis_guides(source=source, target=target, hero_ids=[18]))

    assert report.missing == 6
    assert report.imported == report.already_present == 0
    assert all(operation == "hgetall" for operation, _ in redis.operations)
    assert not (tmp_path / "guides").exists()
