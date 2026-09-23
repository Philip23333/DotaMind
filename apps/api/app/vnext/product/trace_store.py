"""Short-lived, browser-owned persistence for agent-run traces."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict
from redis.exceptions import RedisError


class RunTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    browser_id_hash: str
    session_id: str
    request_id: str
    created_at: datetime
    expires_at: datetime
    status: Literal["completed", "failed", "cancelled"] = "failed"
    recording_mode: Literal["diagnostic", "test"] = "diagnostic"
    trace: dict[str, Any]


class TraceNotFoundError(LookupError):
    pass


class TraceStoreUnavailableError(RuntimeError):
    pass


class TraceStore(Protocol):
    async def put(self, trace: RunTrace) -> None: ...

    async def get(self, trace_id: str) -> RunTrace: ...

    async def list_session(self, session_id: str, *, limit: int = 100) -> list[RunTrace]: ...


class RedisTraceStore:
    STORAGE_SCHEMA_VERSION = 1
    DEFAULT_TTL_SECONDS = 72 * 60 * 60

    def __init__(self, client: Any, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        if ttl_seconds <= 0:
            raise ValueError("trace TTL must be greater than zero")
        self._client = client
        self._ttl_seconds = ttl_seconds

    async def put(self, trace: RunTrace) -> None:
        value = json.dumps(
            {
                "storage_schema_version": self.STORAGE_SCHEMA_VERSION,
                "trace": trace.model_dump(mode="json"),
            },
            separators=(",", ":"),
        )
        await self._call(
            lambda: self._client.set(self.key_for(trace.trace_id), value, ex=self._ttl_seconds)
        )
        index_key = self.session_index_key(trace.session_id)
        try:
            await self._call(
                lambda: self._client.zadd(
                    index_key,
                    {trace.trace_id: trace.created_at.timestamp()},
                )
            )
            await self._call(lambda: self._client.expire(index_key, self._ttl_seconds))
        except Exception:
            try:
                await self._call(lambda: self._client.zrem(index_key, trace.trace_id))
            except Exception:
                pass
            try:
                await self._call(lambda: self._client.delete(self.key_for(trace.trace_id)))
            except Exception:
                pass
            raise

    async def get(self, trace_id: str) -> RunTrace:
        value = await self._call(lambda: self._client.get(self.key_for(trace_id)))
        if value is None:
            raise TraceNotFoundError(trace_id)
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        envelope = json.loads(value)
        if envelope.get("storage_schema_version") != self.STORAGE_SCHEMA_VERSION:
            raise ValueError("unsupported trace storage schema version")
        trace = RunTrace.model_validate(envelope["trace"])
        if trace.trace_id != trace_id:
            raise ValueError("trace key does not match trace payload")
        if trace.expires_at <= datetime.now(UTC):
            await self._remove(trace.trace_id, trace.session_id)
            raise TraceNotFoundError(trace_id)
        return trace

    async def list_session(self, session_id: str, *, limit: int = 100) -> list[RunTrace]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("trace list limit must be between 1 and 100")
        index_key = self.session_index_key(session_id)
        traces: list[RunTrace] = []
        seen: set[str] = set()
        while len(traces) < limit:
            raw_ids = await self._call(lambda: self._client.zrevrange(index_key, 0, 99))
            trace_ids = [_decode(value) for value in raw_ids]
            if not trace_ids:
                break
            new_ids = [trace_id for trace_id in trace_ids if trace_id not in seen]
            if not new_ids:
                break
            for trace_id in new_ids:
                seen.add(trace_id)
                try:
                    trace = await self.get(trace_id)
                except TraceNotFoundError:
                    await self._call(
                        lambda trace_id=trace_id: self._client.zrem(index_key, trace_id)
                    )
                    continue
                if trace.session_id != session_id:
                    await self._call(
                        lambda trace_id=trace_id: self._client.zrem(index_key, trace_id)
                    )
                    continue
                traces.append(trace)
                if len(traces) == limit:
                    break
        return traces

    @classmethod
    def key_for(cls, trace_id: str) -> str:
        return f"dotamind:vnext:trace:v{cls.STORAGE_SCHEMA_VERSION}:{trace_id}"

    @classmethod
    def session_index_key(cls, session_id: str) -> str:
        return f"dotamind:vnext:trace-session:v{cls.STORAGE_SCHEMA_VERSION}:{session_id}"

    async def _remove(self, trace_id: str, session_id: str) -> None:
        await self._call(lambda: self._client.delete(self.key_for(trace_id)))
        await self._call(
            lambda: self._client.zrem(self.session_index_key(session_id), trace_id)
        )

    async def _call(self, operation: Any) -> Any:
        try:
            return await operation()
        except (RedisError, OSError) as exc:
            raise TraceStoreUnavailableError("trace storage is temporarily unavailable") from exc


__all__ = [
    "RunTrace",
    "RedisTraceStore",
    "TraceNotFoundError",
    "TraceStore",
    "TraceStoreUnavailableError",
]


def _decode(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)
