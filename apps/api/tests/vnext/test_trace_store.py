from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.vnext.product.trace_store import (
    RedisTraceStore,
    RunTrace,
    TraceNotFoundError,
    TraceStoreUnavailableError,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttl: dict[str, int] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}
        self.index_ttl: dict[str, int] = {}

    async def set(self, key: str, value: str, *, ex: int) -> bool:
        self.values[key] = value
        self.ttl[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)

    async def zadd(self, key: str, values: dict[str, float]) -> int:
        sorted_set = self.sorted_sets.setdefault(key, {})
        added = sum(member not in sorted_set for member in values)
        sorted_set.update(values)
        return added

    async def expire(self, key: str, ttl: int) -> bool:
        self.index_ttl[key] = ttl
        return True

    async def zrevrange(self, key: str, start: int, stop: int) -> list[str]:
        values = sorted(
            self.sorted_sets.get(key, {}).items(),
            key=lambda item: (item[1], item[0]),
            reverse=True,
        )
        return [member for member, _ in values[start : stop + 1]]

    async def zrem(self, key: str, *members: str) -> int:
        sorted_set = self.sorted_sets.setdefault(key, {})
        removed = 0
        for member in members:
            removed += int(sorted_set.pop(member, None) is not None)
        return removed


class UnavailableRedis:
    async def get(self, _key: str) -> None:
        raise OSError("unavailable")


def _trace(trace_id: str = "trace-1", *, created_at: datetime | None = None) -> RunTrace:
    now = datetime.now(UTC)
    created = created_at or now
    return RunTrace(
        trace_id=trace_id,
        browser_id_hash="hash",
        session_id="session",
        request_id="request",
        created_at=created,
        expires_at=now + timedelta(hours=72),
        trace={"steps": []},
    )


def test_redis_trace_store_round_trips_with_fixed_ttl() -> None:
    client = FakeRedis()
    store = RedisTraceStore(client, ttl_seconds=60)

    asyncio.run(store.put(_trace()))

    assert client.ttl["dotamind:vnext:trace:v1:trace-1"] == 60
    loaded = asyncio.run(store.get("trace-1"))
    assert loaded.browser_id_hash == "hash"
    assert loaded.status == "failed"
    assert loaded.recording_mode == "diagnostic"
    assert client.index_ttl[store.session_index_key("session")] == 60


def test_legacy_failure_records_parse_with_diagnostic_defaults() -> None:
    client = FakeRedis()
    store = RedisTraceStore(client)
    legacy = _trace()
    payload = legacy.model_dump(mode="json")
    payload.pop("status")
    payload.pop("recording_mode")
    client.values[store.key_for(legacy.trace_id)] = json.dumps(
        {"storage_schema_version": 1, "trace": payload}
    )

    loaded = asyncio.run(store.get(legacy.trace_id))

    assert loaded.status == "failed"
    assert loaded.recording_mode == "diagnostic"


def test_expired_trace_is_removed_from_payload_and_session_index() -> None:
    client = FakeRedis()
    store = RedisTraceStore(client)
    trace = _trace("expired").model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    asyncio.run(store.put(trace))

    with pytest.raises(TraceNotFoundError):
        asyncio.run(store.get(trace.trace_id))

    assert store.key_for(trace.trace_id) not in client.values
    assert trace.trace_id not in client.sorted_sets[store.session_index_key(trace.session_id)]


def test_session_index_returns_recent_records_and_prunes_expired_entries() -> None:
    client = FakeRedis()
    store = RedisTraceStore(client)
    now = datetime.now(UTC)
    old = _trace("old", created_at=now - timedelta(minutes=2))
    recent = _trace("recent", created_at=now - timedelta(minutes=1))
    missing_id = "expired"
    asyncio.run(store.put(old))
    asyncio.run(store.put(recent))
    client.sorted_sets[store.session_index_key("session")][missing_id] = now.timestamp()

    listed = asyncio.run(store.list_session("session"))

    assert [trace.trace_id for trace in listed] == ["recent", "old"]
    assert missing_id not in client.sorted_sets[store.session_index_key("session")]


def test_trace_store_put_failure_does_not_leave_a_session_index_entry() -> None:
    class FailingIndexRedis(FakeRedis):
        async def zadd(self, _key: str, _values: dict[str, float]) -> int:
            raise OSError("index unavailable")

    client = FailingIndexRedis()
    store = RedisTraceStore(client)

    with pytest.raises(TraceStoreUnavailableError):
        asyncio.run(store.put(_trace()))

    assert client.values == {}
    assert client.sorted_sets[store.session_index_key("session")] == {}


def test_redis_trace_store_distinguishes_missing_and_unavailable() -> None:
    with pytest.raises(TraceNotFoundError):
        asyncio.run(RedisTraceStore(FakeRedis()).get("missing"))
    with pytest.raises(TraceStoreUnavailableError):
        asyncio.run(RedisTraceStore(UnavailableRedis()).get("trace-1"))
