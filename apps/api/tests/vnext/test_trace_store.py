from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.vnext.product.trace_store import (
    FailedRunTrace,
    RedisTraceStore,
    TraceNotFoundError,
    TraceStoreUnavailableError,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    async def set(self, key: str, value: str, *, ex: int) -> bool:
        self.values[key] = value
        self.ttl[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)


class UnavailableRedis:
    async def get(self, _key: str) -> None:
        raise OSError("unavailable")


def _trace(trace_id: str = "trace-1") -> FailedRunTrace:
    now = datetime.now(UTC)
    return FailedRunTrace(
        trace_id=trace_id,
        browser_id_hash="hash",
        session_id="session",
        request_id="request",
        created_at=now,
        expires_at=now + timedelta(hours=72),
        trace={"steps": []},
    )


def test_redis_trace_store_round_trips_with_fixed_ttl() -> None:
    client = FakeRedis()
    store = RedisTraceStore(client, ttl_seconds=60)

    asyncio.run(store.put(_trace()))

    assert client.ttl["dotamind:vnext:trace:v1:trace-1"] == 60
    assert asyncio.run(store.get("trace-1")).browser_id_hash == "hash"


def test_redis_trace_store_distinguishes_missing_and_unavailable() -> None:
    with pytest.raises(TraceNotFoundError):
        asyncio.run(RedisTraceStore(FakeRedis()).get("missing"))
    with pytest.raises(TraceStoreUnavailableError):
        asyncio.run(RedisTraceStore(UnavailableRedis()).get("trace-1"))
