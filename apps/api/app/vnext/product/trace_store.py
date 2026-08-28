"""Short-lived, browser-owned persistence for failed agent-run traces."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict
from redis.exceptions import RedisError


class FailedRunTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    browser_id_hash: str
    session_id: str
    request_id: str
    created_at: datetime
    expires_at: datetime
    trace: dict[str, Any]


class TraceNotFoundError(LookupError):
    pass


class TraceStoreUnavailableError(RuntimeError):
    pass


class TraceStore(Protocol):
    async def put(self, trace: FailedRunTrace) -> None: ...

    async def get(self, trace_id: str) -> FailedRunTrace: ...


class RedisTraceStore:
    STORAGE_SCHEMA_VERSION = 1
    DEFAULT_TTL_SECONDS = 72 * 60 * 60

    def __init__(self, client: Any, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        if ttl_seconds <= 0:
            raise ValueError("trace TTL must be greater than zero")
        self._client = client
        self._ttl_seconds = ttl_seconds

    async def put(self, trace: FailedRunTrace) -> None:
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

    async def get(self, trace_id: str) -> FailedRunTrace:
        value = await self._call(lambda: self._client.get(self.key_for(trace_id)))
        if value is None:
            raise TraceNotFoundError(trace_id)
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        envelope = json.loads(value)
        if envelope.get("storage_schema_version") != self.STORAGE_SCHEMA_VERSION:
            raise ValueError("unsupported trace storage schema version")
        trace = FailedRunTrace.model_validate(envelope["trace"])
        if trace.trace_id != trace_id:
            raise ValueError("trace key does not match trace payload")
        return trace

    @classmethod
    def key_for(cls, trace_id: str) -> str:
        return f"dotamind:vnext:trace:v{cls.STORAGE_SCHEMA_VERSION}:{trace_id}"

    async def _call(self, operation: Any) -> Any:
        try:
            return await operation()
        except (RedisError, OSError) as exc:
            raise TraceStoreUnavailableError("trace storage is temporarily unavailable") from exc


__all__ = [
    "FailedRunTrace",
    "RedisTraceStore",
    "TraceNotFoundError",
    "TraceStore",
    "TraceStoreUnavailableError",
]
