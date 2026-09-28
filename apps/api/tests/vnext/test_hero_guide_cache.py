from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from redis.exceptions import RedisError

from app.vnext.capabilities.hero.guide import ProMatchExample, PubGuide
from app.vnext.hero_guides.cache import (
    GuideCacheEntry,
    GuideCacheSnapshot,
    HeroGuideCacheDataError,
    HeroGuideCacheUnavailableError,
    RedisHeroGuideCache,
)
from app.vnext.providers.d2pt.parsers import parse_pro_examples, parse_pub_builds

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "d2pt"
_NOW = datetime(2026, 9, 28, 3, 0, tzinfo=UTC)
_ATTEMPTED_BEFORE_RETRIEVAL = _NOW - timedelta(minutes=1)
_PUB_KEY = "dotamind:vnext:hero-guide:v1:pub:18:1"
_PRO_KEY = "dotamind:vnext:hero-guide:v1:pro:18"


class FakeRedis:
    """Small HSET/HGETALL fake that applies each mapping as one operation."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str | bytes, str | bytes]] = {}
        self.hset_calls: list[tuple[str, dict[str, str]]] = []
        self.hgetall_calls: list[str] = []
        self.fail_next_hset = False
        self.fail_hgetall = False
        self.return_bytes = False

    async def hset(self, key: str, *, mapping: dict[str, str]) -> int:
        self.hset_calls.append((key, dict(mapping)))
        if self.fail_next_hset:
            self.fail_next_hset = False
            raise RedisError("CACHE_PRIVATE_SECRET")
        target = self.hashes.setdefault(key, {})
        added = sum(field not in target for field in mapping)
        target.update(mapping)
        return added

    async def hgetall(self, key: str) -> dict[str | bytes, str | bytes]:
        self.hgetall_calls.append(key)
        if self.fail_hgetall:
            raise RedisError("CACHE_PRIVATE_SECRET")
        values = self.hashes.get(key, {})
        if self.return_bytes:
            return {
                field.encode("utf-8") if isinstance(field, str) else field:
                value.encode("utf-8") if isinstance(value, str) else value
                for field, value in values.items()
            }
        return dict(values)


def _run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def _pub_snapshot(
    *,
    hero_id: int = 18,
    position: int | None = 1,
    retrieved_at: datetime = _NOW,
    raw_body: bytes = b"[]",
    source_rows: list[dict[str, Any]] | None = None,
    pub_guides: list[PubGuide] | None = None,
) -> GuideCacheSnapshot:
    return GuideCacheSnapshot(
        sample_type="pub",
        hero_id=hero_id,
        position=position,
        retrieved_at=retrieved_at,
        content_type="application/json",
        raw_body=raw_body,
        source_rows=[] if source_rows is None else source_rows,
        pub_guides=[] if pub_guides is None else pub_guides,
    )


def _pro_snapshot(
    *,
    hero_id: int = 18,
    retrieved_at: datetime = _NOW,
    raw_body: bytes = b"[]",
    source_rows: list[dict[str, Any]] | None = None,
    pro_examples: list[ProMatchExample] | None = None,
) -> GuideCacheSnapshot:
    return GuideCacheSnapshot(
        sample_type="pro",
        hero_id=hero_id,
        position=None,
        retrieved_at=retrieved_at,
        content_type="application/json",
        raw_body=raw_body,
        source_rows=[] if source_rows is None else source_rows,
        pro_examples=[] if pro_examples is None else pro_examples,
    )


def _example(match_id: int, *, position: int) -> ProMatchExample:
    return ProMatchExample(
        source_match_id=match_id,
        hero_id=18,
        position=position,
        position_basis="draft",
        source_path=f"$[0].recent_matches[{match_id}]",
    )


def _source_snapshots() -> tuple[GuideCacheSnapshot, GuideCacheSnapshot]:
    pub_raw = (_FIXTURE_DIR / "pub_sven_pos1.json").read_bytes()
    pub_rows = json.loads(pub_raw)
    pub_snapshot = _pub_snapshot(
        raw_body=pub_raw,
        source_rows=pub_rows,
        pub_guides=parse_pub_builds(pub_rows, hero_id=18, position=1),
    )

    pro_raw = (_FIXTURE_DIR / "pro_sven.json").read_bytes()
    pro_rows = json.loads(pro_raw)
    pro_snapshot = _pro_snapshot(
        raw_body=pro_raw,
        source_rows=pro_rows,
        pro_examples=parse_pro_examples(pro_rows, hero_id=18),
    )
    return pub_snapshot, pro_snapshot


def _redis_hash(
    *,
    snapshot: str | None = None,
    attempted_at: str = _NOW.isoformat(),
    last_error: str = "",
) -> dict[str, str]:
    result = {"last_attempt_at": attempted_at, "last_error": last_error}
    if snapshot is not None:
        result["snapshot"] = snapshot
    return result


def test_empty_pub_and_pro_partitions_return_empty_entries() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)

    pub_entry = _run(cache.get_pub(hero_id=18, position=1))
    pro_entry = _run(cache.get_pro(hero_id=18))

    assert pub_entry == GuideCacheEntry()
    assert pro_entry == GuideCacheEntry()
    assert client.hgetall_calls == [_PUB_KEY, _PRO_KEY]


def test_fixture_snapshots_round_trip_raw_source_and_parsed_dtos() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)
    pub_snapshot, pro_snapshot = _source_snapshots()

    _run(cache.publish(pub_snapshot, attempted_at=_ATTEMPTED_BEFORE_RETRIEVAL))
    _run(cache.publish(pro_snapshot, attempted_at=_ATTEMPTED_BEFORE_RETRIEVAL))
    pub_entry = _run(cache.get_pub(hero_id=18, position=1))
    pro_entry = _run(cache.get_pro(hero_id=18))

    assert pub_entry.snapshot is not None
    assert pub_entry.snapshot.raw_body == pub_snapshot.raw_body
    assert pub_entry.snapshot.source_rows == pub_snapshot.source_rows
    assert pub_entry.snapshot.pub_guides == pub_snapshot.pub_guides
    assert pub_entry.snapshot.retrieved_at == pub_snapshot.retrieved_at
    assert pub_entry.last_attempt_at == _ATTEMPTED_BEFORE_RETRIEVAL
    assert pub_entry.last_error is None
    assert pro_entry.snapshot is not None
    assert pro_entry.snapshot.raw_body == pro_snapshot.raw_body
    assert pro_entry.snapshot.source_rows == pro_snapshot.source_rows
    assert pro_entry.snapshot.pro_examples == pro_snapshot.pro_examples
    assert pro_entry.snapshot.retrieved_at == pro_snapshot.retrieved_at


def test_pro_zero_ability_event_round_trips_through_fake_redis() -> None:
    source_rows = [
        {
            "hero_id": 18,
            "position": "pos 1",
            "recent_matches": [
                {
                    "match_id": 900,
                    "hero_id": 18,
                    "abilities": [
                        {
                            "ability_id": 0,
                            "time": 1105,
                            "level": 14,
                            "unknown": {"kept": [0, False, None]},
                        }
                    ],
                }
            ],
        }
    ]
    raw_body = json.dumps(source_rows, separators=(",", ":")).encode("utf-8")
    examples = parse_pro_examples(source_rows, hero_id=18)
    snapshot = _pro_snapshot(
        raw_body=raw_body,
        source_rows=source_rows,
        pro_examples=examples,
    )
    cache = RedisHeroGuideCache(FakeRedis())

    _run(cache.publish(snapshot, attempted_at=_NOW))
    loaded = _run(cache.get_pro(hero_id=18)).snapshot

    assert loaded is not None
    assert loaded.raw_body == raw_body
    event = loaded.pro_examples[0].ability_timeline[0]
    assert event.ability_id == 0
    assert type(event.ability_id) is int
    assert event.time_seconds == 1105
    assert event.hero_level == 14
    assert event.source_fields == source_rows[0]["recent_matches"][0]["abilities"][0]


def test_second_cache_instance_reads_published_data_from_shared_redis() -> None:
    client = FakeRedis()
    first_cache = RedisHeroGuideCache(client)
    _run(first_cache.publish(_pub_snapshot(), attempted_at=_NOW))

    second_cache = RedisHeroGuideCache(client)
    loaded = _run(second_cache.get_pub(hero_id=18, position=1))

    assert loaded.snapshot == _pub_snapshot()


def test_pub_hero_position_and_pro_partitions_are_isolated() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)
    _run(cache.publish(_pub_snapshot(), attempted_at=_NOW))
    _run(cache.publish(_pub_snapshot(position=2), attempted_at=_NOW))
    _run(cache.publish(_pub_snapshot(hero_id=19), attempted_at=_NOW))
    _run(cache.publish(_pro_snapshot(), attempted_at=_NOW))

    assert _run(cache.get_pub(hero_id=18, position=1)).snapshot == _pub_snapshot()
    assert _run(cache.get_pub(hero_id=18, position=2)).snapshot == _pub_snapshot(position=2)
    assert _run(cache.get_pub(hero_id=19, position=1)).snapshot == _pub_snapshot(hero_id=19)
    assert _run(cache.get_pro(hero_id=18)).snapshot == _pro_snapshot()
    assert set(client.hashes) == {
        _PUB_KEY,
        "dotamind:vnext:hero-guide:v1:pub:18:2",
        "dotamind:vnext:hero-guide:v1:pub:19:1",
        _PRO_KEY,
    }


def test_pro_publish_replaces_the_whole_hero_snapshot_across_positions() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)
    first = _pro_snapshot(pro_examples=[_example(1, position=1), _example(2, position=2)])
    replacement = _pro_snapshot(pro_examples=[_example(3, position=2)])

    _run(cache.publish(first, attempted_at=_NOW))
    _run(cache.publish(replacement, attempted_at=_NOW + timedelta(minutes=1)))
    loaded = _run(cache.get_pro(hero_id=18))

    assert loaded.snapshot is not None
    assert loaded.snapshot.pro_examples == [_example(3, position=2)]


def test_successful_empty_snapshot_replaces_previous_nonempty_snapshot() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)
    nonempty = _pub_snapshot(
        source_rows=[{"hero_id": 18, "build_data": {"keep": True}}],
        pub_guides=[PubGuide(build_id=4)],
    )
    empty = _pub_snapshot(raw_body=b"[]", source_rows=[], pub_guides=[])

    _run(cache.publish(nonempty, attempted_at=_NOW))
    _run(cache.publish(empty, attempted_at=_NOW + timedelta(minutes=1)))
    loaded = _run(cache.get_pub(hero_id=18, position=1))

    assert loaded.snapshot is not None
    assert loaded.snapshot.raw_body == b"[]"
    assert loaded.snapshot.source_rows == []
    assert loaded.snapshot.pub_guides == []


def test_pro_nonempty_source_without_recent_matches_is_still_a_snapshot() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)
    source_rows = [{"hero_id": 18, "position": "pos 1", "recent_matches": []}]
    snapshot = _pro_snapshot(source_rows=source_rows, pro_examples=[])

    _run(cache.publish(snapshot, attempted_at=_NOW))
    loaded = _run(cache.get_pro(hero_id=18))

    assert loaded.snapshot is not None
    assert loaded.snapshot.source_rows == source_rows
    assert loaded.snapshot.pro_examples == []


def test_first_failure_creates_attempt_state_without_snapshot() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)

    _run(
        cache.record_failure(
            sample_type="pub",
            hero_id=18,
            position=1,
            attempted_at=_NOW,
            error_code="timeout",
        )
    )
    entry = _run(cache.get_pub(hero_id=18, position=1))

    assert entry.snapshot is None
    assert entry.last_attempt_at == _NOW
    assert entry.last_error == "timeout"
    assert client.hashes[_PUB_KEY] == {
        "last_attempt_at": _NOW.isoformat(),
        "last_error": "timeout",
    }


def test_failure_after_success_preserves_snapshot_and_only_updates_attempt_state() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)
    original = _pub_snapshot(raw_body=b"original-bytes", pub_guides=[PubGuide(build_id=3)])
    _run(cache.publish(original, attempted_at=_NOW))
    original_hash = dict(client.hashes[_PUB_KEY])

    _run(
        cache.record_failure(
            sample_type="pub",
            hero_id=18,
            position=1,
            attempted_at=_NOW + timedelta(minutes=4),
            error_code="http_error",
        )
    )
    entry = _run(cache.get_pub(hero_id=18, position=1))

    assert entry.snapshot is not None
    assert entry.snapshot.raw_body == b"original-bytes"
    assert entry.snapshot.pub_guides == original.pub_guides
    assert entry.snapshot.retrieved_at == original.retrieved_at
    assert entry.last_attempt_at == _NOW + timedelta(minutes=4)
    assert entry.last_error == "http_error"
    assert client.hashes[_PUB_KEY]["snapshot"] == original_hash["snapshot"]


def test_success_after_failure_replaces_snapshot_and_clears_error() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)
    _run(
        cache.record_failure(
            sample_type="pro",
            hero_id=18,
            attempted_at=_NOW,
            error_code="transport_error",
        )
    )

    snapshot = _pro_snapshot(raw_body=b"new-data")
    _run(cache.publish(snapshot, attempted_at=_NOW + timedelta(minutes=1)))
    entry = _run(cache.get_pro(hero_id=18))

    assert entry.snapshot == snapshot
    assert entry.last_attempt_at == _NOW + timedelta(minutes=1)
    assert entry.last_error is None


def test_failure_for_one_source_does_not_change_other_source() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)
    pro_snapshot = _pro_snapshot(raw_body=b"pro")
    _run(cache.publish(_pub_snapshot(raw_body=b"pub"), attempted_at=_NOW))
    _run(cache.publish(pro_snapshot, attempted_at=_NOW))
    _run(
        cache.record_failure(
            sample_type="pub",
            hero_id=18,
            position=1,
            attempted_at=_NOW + timedelta(minutes=2),
            error_code="invalid_guide_data",
        )
    )

    pub_entry = _run(cache.get_pub(hero_id=18, position=1))
    pro_entry = _run(cache.get_pro(hero_id=18))

    assert pub_entry.last_error == "invalid_guide_data"
    assert pro_entry.snapshot == pro_snapshot
    assert pro_entry.last_error is None


def test_publish_uses_one_hset_with_all_three_fields() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)

    _run(cache.publish(_pub_snapshot(), attempted_at=_NOW))

    assert len(client.hset_calls) == 1
    key, mapping = client.hset_calls[0]
    assert key == _PUB_KEY
    assert set(mapping) == {"snapshot", "last_attempt_at", "last_error"}
    assert mapping["last_attempt_at"] == _NOW.isoformat()
    assert mapping["last_error"] == ""


def test_record_failure_uses_one_hset_without_snapshot_field() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)

    _run(
        cache.record_failure(
            sample_type="pro",
            hero_id=18,
            attempted_at=_NOW,
            error_code="timeout",
        )
    )

    assert len(client.hset_calls) == 1
    key, mapping = client.hset_calls[0]
    assert key == _PRO_KEY
    assert mapping == {"last_attempt_at": _NOW.isoformat(), "last_error": "timeout"}
    assert "snapshot" not in mapping


def test_each_read_uses_one_hgetall() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)

    _run(cache.get_pub(hero_id=18, position=1))
    _run(cache.get_pro(hero_id=18))

    assert client.hgetall_calls == [_PUB_KEY, _PRO_KEY]


def test_redis_error_before_write_preserves_old_hash_without_claiming_commit_ambiguity() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)
    _run(cache.publish(_pub_snapshot(raw_body=b"old"), attempted_at=_NOW))
    old_hash = dict(client.hashes[_PUB_KEY])
    client.fail_next_hset = True

    with pytest.raises(HeroGuideCacheUnavailableError) as exc_info:
        _run(cache.publish(_pub_snapshot(raw_body=b"new"), attempted_at=_NOW))

    assert "CACHE_PRIVATE_SECRET" not in str(exc_info.value)
    assert client.hashes[_PUB_KEY] == old_hash
    assert len(client.hset_calls) == 2


def test_redis_read_error_is_not_a_cache_miss() -> None:
    client = FakeRedis()
    client.fail_hgetall = True

    with pytest.raises(HeroGuideCacheUnavailableError) as exc_info:
        _run(RedisHeroGuideCache(client).get_pub(hero_id=18, position=1))

    assert "CACHE_PRIVATE_SECRET" not in str(exc_info.value)
    assert len(client.hgetall_calls) == 1


@pytest.mark.parametrize(
    "case",
    ["invalid_json", "invalid_base64", "naive_attempt", "mismatched_identity", "missing_state"],
)
def test_corrupt_hash_is_reported_as_data_error_without_deleting_it(case: str) -> None:
    client = FakeRedis()
    key = _PUB_KEY
    snapshot = _pub_snapshot().model_dump_json()
    data = _redis_hash(snapshot=snapshot)

    if case == "invalid_json":
        data["snapshot"] = '{"marker":"CACHE_PRIVATE_SECRET"'
    elif case == "invalid_base64":
        malformed = json.loads(snapshot)
        malformed["raw_body"] = "%%%not-base64%%%"
        data["snapshot"] = json.dumps(malformed)
    elif case == "naive_attempt":
        data["last_attempt_at"] = "2026-09-28T03:00:00"
    elif case == "mismatched_identity":
        data["snapshot"] = _pub_snapshot(hero_id=19).model_dump_json()
    else:
        data.pop("last_error")

    client.hashes[key] = dict(data)
    original = dict(client.hashes[key])
    cache = RedisHeroGuideCache(client)

    with pytest.raises(HeroGuideCacheDataError) as exc_info:
        _run(cache.get_pub(hero_id=18, position=1))

    assert "CACHE_PRIVATE_SECRET" not in str(exc_info.value)
    assert client.hashes[key] == original
    assert len(client.hgetall_calls) == 1


def test_success_status_without_snapshot_is_corrupt() -> None:
    client = FakeRedis()
    client.hashes[_PUB_KEY] = {"last_attempt_at": _NOW.isoformat(), "last_error": ""}

    with pytest.raises(HeroGuideCacheDataError):
        _run(RedisHeroGuideCache(client).get_pub(hero_id=18, position=1))


def test_bom_and_non_ascii_raw_body_round_trip_as_exact_bytes() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)
    raw = "\ufeff{\"message\":\"攻略雪\"}".encode("utf-8")
    snapshot = _pub_snapshot(raw_body=raw)

    _run(cache.publish(snapshot, attempted_at=_NOW))
    stored_json = json.loads(client.hashes[_PUB_KEY]["snapshot"])
    expected_base64 = base64.urlsafe_b64encode(raw).decode("ascii")
    loaded = _run(cache.get_pub(hero_id=18, position=1))

    assert stored_json["raw_body"] == expected_base64
    assert loaded.snapshot is not None
    assert loaded.snapshot.raw_body == raw


def test_redis_bytes_keys_and_values_are_supported() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)
    _run(cache.publish(_pub_snapshot(raw_body=b"body"), attempted_at=_NOW))
    client.return_bytes = True

    entry = _run(cache.get_pub(hero_id=18, position=1))

    assert entry.snapshot is not None
    assert entry.snapshot.raw_body == b"body"


def test_mutating_snapshot_input_or_read_result_does_not_change_saved_data() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)
    rows = [{"hero_id": 18, "extra": {"values": [None, 0, False]}}]
    snapshot = _pub_snapshot(source_rows=rows)

    _run(cache.publish(snapshot, attempted_at=_NOW))
    rows[0]["extra"]["values"].append("mutated-input")
    first_read = _run(cache.get_pub(hero_id=18, position=1))
    assert first_read.snapshot is not None
    first_read.snapshot.source_rows[0]["extra"]["values"].append("mutated-read")
    second_read = _run(cache.get_pub(hero_id=18, position=1))

    assert second_read.snapshot is not None
    assert second_read.snapshot.source_rows == [
        {"hero_id": 18, "extra": {"values": [None, 0, False]}}
    ]


def test_model_validation_failure_does_not_write_redis() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)
    snapshot = _pub_snapshot(source_rows=[{"hero_id": 18, "nested": {"value": 1.0}}])
    snapshot.source_rows[0]["nested"]["value"] = float("nan")

    with pytest.raises(HeroGuideCacheDataError):
        _run(cache.publish(snapshot, attempted_at=_NOW))

    assert client.hset_calls == []
    assert client.hashes == {}


def test_invalid_partition_arguments_and_error_codes_fail_before_redis_io() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)

    invalid_reads = [
        lambda: cache.get_pub(hero_id=True, position=1),
        lambda: cache.get_pub(hero_id=18, position=True),
        lambda: cache.get_pub(hero_id=18, position=6),
        lambda: cache.get_pro(hero_id=0),
    ]
    for call in invalid_reads:
        with pytest.raises(ValueError):
            _run(call())

    invalid_failures = [
        lambda: cache.record_failure(
            sample_type="pub", hero_id=18, attempted_at=_NOW, error_code="timeout"
        ),
        lambda: cache.record_failure(
            sample_type="pro", hero_id=18, position=1, attempted_at=_NOW, error_code="timeout"
        ),
        lambda: cache.record_failure(
            sample_type="pub",
            hero_id=18,
            position=1,
            attempted_at=datetime(2026, 9, 28),
            error_code="timeout",
        ),
        lambda: cache.record_failure(
            sample_type="pub",
            hero_id=18,
            position=1,
            attempted_at=_NOW,
            error_code="CACHE_PRIVATE_SECRET",
        ),
    ]
    for call in invalid_failures:
        with pytest.raises(ValueError):
            _run(call())

    assert client.hgetall_calls == []
    assert client.hset_calls == []


@pytest.mark.parametrize(
    "values",
    [
        {"sample_type": "pub", "position": None},
        {"sample_type": "pro", "position": 1},
        {"sample_type": "pub", "position": True},
        {"sample_type": "pub", "position": 6},
        {"sample_type": "pub", "hero_id": True, "position": 1},
        {"sample_type": "pub", "retrieved_at": datetime(2026, 9, 28)},
        {"sample_type": "pub", "raw_body": "not-bytes"},
        {"sample_type": "pub", "pub_guides": [], "pro_examples": [_example(1, position=1)]},
        {"sample_type": "pro", "pub_guides": [PubGuide()], "pro_examples": []},
    ],
)
def test_snapshot_rejects_invalid_partition_or_field_values(values: dict[str, Any]) -> None:
    parameters: dict[str, Any] = {
        "sample_type": "pub",
        "hero_id": 18,
        "position": 1,
        "retrieved_at": _NOW,
        "content_type": "application/json",
        "raw_body": b"[]",
        "source_rows": [],
    }
    parameters.update(values)

    with pytest.raises(ValidationError):
        GuideCacheSnapshot(**parameters)


def test_read_returns_independent_open_objects_on_each_call() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)
    _run(
        cache.publish(
            _pub_snapshot(source_rows=[{"hero_id": 18, "future": {"values": [1]}}]),
            attempted_at=_NOW,
        )
    )

    first = _run(cache.get_pub(hero_id=18, position=1))
    assert first.snapshot is not None
    first.snapshot.source_rows[0]["future"]["values"].append(2)
    second = _run(cache.get_pub(hero_id=18, position=1))

    assert second.snapshot is not None
    assert second.snapshot.source_rows[0]["future"]["values"] == [1]


def test_cache_does_not_reject_attempt_started_before_response_retrieval() -> None:
    client = FakeRedis()
    cache = RedisHeroGuideCache(client)

    _run(cache.publish(_pub_snapshot(retrieved_at=_NOW), attempted_at=_ATTEMPTED_BEFORE_RETRIEVAL))
    entry = _run(cache.get_pub(hero_id=18, position=1))

    assert entry.last_attempt_at == _ATTEMPTED_BEFORE_RETRIEVAL
    assert entry.snapshot is not None
    assert entry.snapshot.retrieved_at == _NOW
