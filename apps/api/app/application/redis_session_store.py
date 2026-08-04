"""Redis-backed SessionStore with fenced distributed session transactions."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import time
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any
from uuid import UUID, uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError

from app.agentic.conversation.models import Turn
from app.application.idempotency import RequestBeginResult, RequestFailAction, RequestRecord
from app.application.redis_models import (
    deserialize_request_record,
    deserialize_turn,
    serialize_request_record,
    serialize_turn,
)
from app.application.session_store import SessionStore, SessionStoreError
from app.observability import (
    emit_event,
    record_idempotency,
    record_lock_wait,
    record_session_operation,
)

_SCHEMA_VERSION = "1"
logger = logging.getLogger(__name__)


def _observe_session_operation(operation: str, *, record_success: bool = True):
    def decorate(function):
        @wraps(function)
        async def observed(self, *args, **kwargs):
            try:
                result = await function(self, *args, **kwargs)
            except SessionStoreError as exc:
                record_session_operation(
                    self.backend_name,
                    operation,
                    "error",
                    exc.code,
                )
                emit_event(
                    logger,
                    "session_store_failed",
                    status="error",
                    failure_code=exc.code,
                    backend=self.backend_name,
                    operation=operation,
                )
                raise
            if record_success:
                record_session_operation(self.backend_name, operation, "ok")
            return result

        return observed

    return decorate

_ACQUIRE_LUA = """
local existing_schema = redis.call('HGET', KEYS[2], 'schema_version')
if existing_schema and existing_schema ~= ARGV[2] then return {-1, 'data_invalid'} end
if redis.call('EXISTS', KEYS[1]) == 1 then return {0, 'busy'} end
local fencing = redis.call('HINCRBY', KEYS[2], 'fencing_counter', 1)
redis.call('HSET', KEYS[2], 'schema_version', ARGV[2])
local value = cjson.encode({owner_token=ARGV[1], fencing_token=fencing})
redis.call('SET', KEYS[1], value, 'PX', ARGV[3])
for index = 2, #KEYS do
  if redis.call('EXISTS', KEYS[index]) == 1 then redis.call('EXPIRE', KEYS[index], ARGV[4]) end
end
return {1, tostring(fencing), value}
"""

_RENEW_LUA = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return {0, 'lock_lost'} end
redis.call('PEXPIRE', KEYS[1], ARGV[2])
for index = 2, #KEYS do
  if redis.call('EXISTS', KEYS[index]) == 1 then redis.call('EXPIRE', KEYS[index], ARGV[3]) end
end
return {1, 'ok'}
"""

_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call('DEL', KEYS[1])
"""

_APPEND_LUA = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return {0, 'lock_lost'} end
local schema = redis.call('HGET', KEYS[2], 'schema_version')
if schema and schema ~= ARGV[5] then return {0, 'data_invalid'} end
redis.call('HSET', KEYS[2], 'schema_version', ARGV[5])
local index = redis.call('HINCRBY', KEYS[2], 'turn_counter', 1)
-- Redis Lua cjson conflates empty arrays and objects.  The Python serializer
-- has already validated this compact Turn, so change only its turn_index in
-- the canonical JSON string and preserve all other JSON types verbatim.
local stored, changed = string.gsub(
  ARGV[2],
  '"turn_index":%d+},"schema_version":' .. ARGV[5] .. '}$',
  '"turn_index":' .. index .. '},"schema_version":' .. ARGV[5] .. '}',
  1
)
if changed ~= 1 then return {0, 'data_invalid'} end
redis.call('RPUSH', KEYS[3], stored)
redis.call('LTRIM', KEYS[3], -tonumber(ARGV[3]), -1)
for key_index = 2, #KEYS do
  if redis.call('EXISTS', KEYS[key_index]) == 1 then
    redis.call('EXPIRE', KEYS[key_index], ARGV[4])
  end
end
return {1, tostring(index), stored}
"""

_BEGIN_REQUEST_LUA = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return {'lock_lost'} end
local schema = redis.call('HGET', KEYS[2], 'schema_version')
if schema and schema ~= ARGV[7] then return {'data_invalid'} end
redis.call('HSET', KEYS[2], 'schema_version', ARGV[7])
local expired = redis.call('ZRANGEBYSCORE', KEYS[4], '-inf', ARGV[4])
for _, member in ipairs(expired) do
  redis.call('HDEL', KEYS[3], member)
  redis.call('ZREM', KEYS[4], member)
end
local existing = redis.call('HGET', KEYS[3], ARGV[2])
if ARGV[8] == 'new' then
  if existing then return {'data_invalid'} end
  while redis.call('ZCARD', KEYS[4]) >= tonumber(ARGV[5]) do
    local oldest = redis.call('ZRANGE', KEYS[4], 0, 0)
    if #oldest == 0 then break end
    redis.call('HDEL', KEYS[3], oldest[1])
    redis.call('ZREM', KEYS[4], oldest[1])
  end
elseif ARGV[8] == 'takeover' then
  if not existing or existing ~= ARGV[9] then return {'data_invalid'} end
else
  return {'data_invalid'}
end
redis.call('HSET', KEYS[3], ARGV[2], ARGV[3])
redis.call('ZREM', KEYS[4], ARGV[2])
for key_index = 2, #KEYS do
  if redis.call('EXISTS', KEYS[key_index]) == 1 then
    redis.call('EXPIRE', KEYS[key_index], ARGV[6])
  end
end
return {'execute'}
"""

_COMPLETE_LUA = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return {0, 'lock_lost'} end
local schema = redis.call('HGET', KEYS[2], 'schema_version')
if schema and schema ~= ARGV[9] then return {0, 'data_invalid'} end
local existing = redis.call('HGET', KEYS[4], ARGV[2])
if not existing or existing ~= ARGV[6] then return {0, 'lock_lost'} end
local record = cjson.decode(existing)
if record.data.status ~= 'in_progress' or record.data.owner_token ~= ARGV[3] then
  return {0, 'lock_lost'}
end
local index = redis.call('HINCRBY', KEYS[2], 'turn_counter', 1)
-- Preserve JSON's [] versus {} distinction; see _APPEND_LUA above.
local turn, changed = string.gsub(
  ARGV[4],
  '"turn_index":%d+},"schema_version":' .. ARGV[9] .. '}$',
  '"turn_index":' .. index .. '},"schema_version":' .. ARGV[9] .. '}',
  1
)
if changed ~= 1 then return {0, 'data_invalid'} end
redis.call('RPUSH', KEYS[3], turn)
redis.call('LTRIM', KEYS[3], -tonumber(ARGV[5]), -1)
local completed, completed_changed = string.gsub(
  ARGV[7],
  '"turn_index":0},"schema_version":1}$',
  '"turn_index":' .. index .. '},"schema_version":1}',
  1
)
if completed_changed ~= 1 then return {0, 'data_invalid'} end
redis.call('HSET', KEYS[4], ARGV[2], completed)
redis.call('ZADD', KEYS[5], ARGV[8], ARGV[2])
redis.call('HSET', KEYS[2], 'schema_version', ARGV[9])
for key_index = 2, #KEYS do
  if redis.call('EXISTS', KEYS[key_index]) == 1 then
    redis.call('EXPIRE', KEYS[key_index], ARGV[10])
  end
end
return {1, tostring(index), turn}
"""

_FAIL_LUA = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return {0, 'lock_lost'} end
local schema = redis.call('HGET', KEYS[2], 'schema_version')
if schema and schema ~= ARGV[8] then return {0, 'data_invalid'} end
local existing = redis.call('HGET', KEYS[3], ARGV[2])
if not existing then return {1, 'noop'} end
if existing ~= ARGV[4] then return {0, 'lock_lost'} end
local record = cjson.decode(existing)
if record.data.status ~= 'in_progress' or record.data.owner_token ~= ARGV[3] then
  return {1, 'noop'}
end
redis.call('HSET', KEYS[3], ARGV[2], ARGV[5])
redis.call('ZADD', KEYS[4], ARGV[6], ARGV[2])
for key_index = 2, #KEYS do
  if redis.call('EXISTS', KEYS[key_index]) == 1 then
    redis.call('EXPIRE', KEYS[key_index], ARGV[7])
  end
end
return {1, 'ok'}
"""


@dataclass
class RedisTransactionContext:
    session_id: str
    base: str
    owner_token: UUID
    fencing_token: int
    lock_value: str
    renewal_task: asyncio.Task[None] | None = None
    lock_lost: bool = False


class RedisSessionStore(SessionStore):
    """SessionStore backed by one Redis primary and fenced session locks."""

    backend_name = "redis"

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        redis: Redis | None = None,
        max_turns_per_session: int = 50,
        request_record_ttl_seconds: int = 3600,
        max_request_records_per_session: int = 200,
        session_ttl_seconds: int = 86400,
        lock_lease_seconds: int = 90,
        lock_acquire_timeout_seconds: int = 60,
        key_prefix: str = "dotamind:v1",
    ) -> None:
        if redis is None and redis_url is None:
            raise ValueError("redis_url or redis client is required")
        self._redis = redis or Redis.from_url(redis_url, decode_responses=True)
        self._max_turns = max_turns_per_session
        self._request_ttl = request_record_ttl_seconds
        self._max_request_records = max_request_records_per_session
        self._session_ttl = session_ttl_seconds
        self._lease_ms = lock_lease_seconds * 1000
        self._acquire_timeout = lock_acquire_timeout_seconds
        self._renew_interval = min(lock_lease_seconds, session_ttl_seconds) / 3
        self._key_prefix = key_prefix.rstrip(":")
        self._contexts: dict[asyncio.Task[object], dict[str, RedisTransactionContext]] = {}

    @_observe_session_operation("ping")
    async def ping(self) -> None:
        try:
            await self._redis.ping()
        except (OSError, RedisError) as exc:
            raise SessionStoreError("unavailable") from exc

    @_observe_session_operation("close")
    async def aclose(self) -> None:
        try:
            await self._redis.aclose()
        except (OSError, RedisError) as exc:
            raise SessionStoreError("unavailable") from exc

    @_observe_session_operation("get")
    async def get(self, session_id: str, limit: int) -> list[Turn]:
        keys = self._keys(session_id)
        try:
            async with self._redis.pipeline(transaction=False) as pipe:
                pipe.hget(keys["meta"], "schema_version")
                pipe.lrange(keys["turns"], -limit, -1)
                schema, raw_turns = await pipe.execute()
        except (OSError, RedisError) as exc:
            raise SessionStoreError("unavailable") from exc
        if schema is None:
            if raw_turns:
                raise SessionStoreError("data_invalid")
            return []
        if str(schema) != _SCHEMA_VERSION:
            raise SessionStoreError("data_invalid")
        try:
            turns = [deserialize_turn(str(value)) for value in raw_turns]
        except ValueError as exc:
            raise SessionStoreError("data_invalid") from exc
        return sorted(turns, key=lambda turn: turn.turn_index)

    @_observe_session_operation("append")
    async def append(self, session_id: str, turn: Turn) -> Turn:
        context = self._require_context(session_id)
        result = await self._eval(
            _APPEND_LUA,
            self._data_keys(context.base),
            context.lock_value,
            serialize_turn(turn),
            str(self._max_turns),
            str(self._session_ttl),
            _SCHEMA_VERSION,
        )
        self._raise_write_failure(result)
        try:
            return deserialize_turn(str(result[2]))
        except (IndexError, ValueError) as exc:
            raise SessionStoreError("data_invalid") from exc

    @_observe_session_operation("begin_request", record_success=False)
    async def begin_request(
        self,
        session_id: str,
        request_id: UUID,
        payload_hash: str,
    ) -> RequestBeginResult:
        context = self._require_context(session_id)
        now = datetime.now(UTC)
        request_key = self.request_key_hash(request_id)
        existing = await self._read_request_record(context, request_id, request_key)
        mode = "new"
        expected_record = ""
        if existing is not None:
            raw_existing, stored_record = existing
            if (
                stored_record.status != "in_progress"
                and stored_record.expires_at <= now
            ):
                mode = "new"
            elif stored_record.payload_hash != payload_hash:
                record_session_operation("redis", "begin_request", "ok")
                return RequestBeginResult(
                    action="conflict",
                    existing_payload_hash=stored_record.payload_hash,
                )
            elif stored_record.status == "completed":
                if stored_record.cached_public_response is None:
                    raise SessionStoreError("data_invalid")
                record_session_operation("redis", "begin_request", "ok")
                return RequestBeginResult(
                    action="replay",
                    cached_public_response=stored_record.cached_public_response,
                )
            else:
                mode = "takeover"
                expected_record = raw_existing
        record = RequestRecord(
            request_id=request_id,
            payload_hash=payload_hash,
            status="in_progress",
            owner_token=uuid4(),
            started_at=now,
            expires_at=now + timedelta(seconds=self._request_ttl),
        )
        result = await self._eval(
            _BEGIN_REQUEST_LUA,
            [
                self._keys_from_base(context.base)["lock"],
                self._keys_from_base(context.base)["meta"],
                self._keys_from_base(context.base)["requests"],
                self._keys_from_base(context.base)["request_gc"],
                self._keys_from_base(context.base)["turns"],
            ],
            context.lock_value,
            request_key,
            serialize_request_record(record),
            str(now.timestamp()),
            str(self._max_request_records),
            str(self._session_ttl),
            _SCHEMA_VERSION,
            mode,
            expected_record,
        )
        action = str(result[0])
        if action == "lock_lost":
            context.lock_lost = True
            raise SessionStoreError("lock_lost")
        if action == "data_invalid":
            raise SessionStoreError("data_invalid")
        if action != "execute":
            raise SessionStoreError("data_invalid")
        record_session_operation("redis", "begin_request", "ok")
        return RequestBeginResult(
            action="execute",
            claim_kind="takeover" if mode == "takeover" else "new",
            owner_token=record.owner_token,
        )

    @_observe_session_operation("complete_request", record_success=False)
    async def complete_request_with_turn(
        self,
        session_id: str,
        request_id: UUID,
        owner_token: UUID,
        turn: Turn,
        public_response: dict[str, Any],
        run_id: UUID,
    ) -> Turn:
        context = self._require_context(session_id)
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self._request_ttl)
        request_key = self.request_key_hash(request_id)
        existing = await self._read_request_record(context, request_id, request_key)
        if existing is None:
            raise SessionStoreError("lock_lost")
        raw_existing, stored_record = existing
        if stored_record.status != "in_progress" or stored_record.owner_token != owner_token:
            raise SessionStoreError("lock_lost")
        completed_record = stored_record.model_copy(
            update={
                "status": "completed",
                "run_id": run_id,
                "cached_public_response": copy.deepcopy(public_response),
                "turn_index": 0,
                "completed_at": now,
                "expires_at": expires_at,
            }
        )
        try:
            result = await self._eval(
                _COMPLETE_LUA,
                self._data_keys(context.base),
                context.lock_value,
                request_key,
                str(owner_token),
                serialize_turn(turn),
                str(self._max_turns),
                raw_existing,
                serialize_request_record(completed_record),
                str(expires_at.timestamp()),
                _SCHEMA_VERSION,
                str(self._session_ttl),
            )
        except asyncio.CancelledError:
            committed = await self._request_is_completed(
                context,
                request_id,
                request_key,
                owner_token,
            )
            emit_event(
                logger,
                "request_commit_cancelled",
                status="completed" if committed else "cancelled",
                backend=self.backend_name,
                operation="complete_request",
            )
            if committed:
                record_session_operation("redis", "complete_request", "ok")
                record_idempotency("redis", "executed")
            else:
                record_session_operation(
                    "redis",
                    "complete_request",
                    "error",
                    "request_cancelled",
                )
            raise
        self._raise_write_failure(result)
        try:
            stored_turn = deserialize_turn(str(result[2]))
        except (IndexError, ValueError) as exc:
            raise SessionStoreError("data_invalid") from exc
        record_session_operation("redis", "complete_request", "ok")
        record_idempotency("redis", "executed")
        return stored_turn

    @_observe_session_operation("fail_request", record_success=False)
    async def fail_request(
        self,
        session_id: str,
        request_id: UUID,
        owner_token: UUID,
    ) -> RequestFailAction:
        context = self._require_context(session_id)
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self._request_ttl)
        request_key = self.request_key_hash(request_id)
        existing = await self._read_request_record(context, request_id, request_key)
        if existing is None:
            record_session_operation("redis", "fail_request", "noop")
            return "noop"
        raw_existing, stored_record = existing
        if stored_record.status == "completed":
            record_session_operation("redis", "fail_request", "noop")
            return "completed"
        if stored_record.status != "in_progress" or stored_record.owner_token != owner_token:
            record_session_operation("redis", "fail_request", "noop")
            return "noop"
        failed_record = stored_record.model_copy(
            update={
                "status": "failed",
                "completed_at": now,
                "expires_at": expires_at,
            }
        )
        result = await self._eval(
            _FAIL_LUA,
            [
                self._keys_from_base(context.base)["lock"],
                self._keys_from_base(context.base)["meta"],
                self._keys_from_base(context.base)["requests"],
                self._keys_from_base(context.base)["request_gc"],
                self._keys_from_base(context.base)["turns"],
            ],
            context.lock_value,
            request_key,
            str(owner_token),
            raw_existing,
            serialize_request_record(failed_record),
            str(expires_at.timestamp()),
            str(self._session_ttl),
            _SCHEMA_VERSION,
        )
        self._raise_write_failure(result)
        record_session_operation("redis", "fail_request", "ok")
        return "failed" if len(result) > 1 and str(result[1]) == "ok" else "noop"

    @asynccontextmanager
    async def transaction(self, session_id: str) -> AbstractAsyncContextManager[None]:
        context = await self._acquire(session_id)
        task = asyncio.current_task()
        if task is None:  # pragma: no cover - asyncio always supplies a task.
            raise RuntimeError("SessionStore.transaction() requires an asyncio task")
        task_contexts = self._contexts.setdefault(task, {})
        if session_id in task_contexts:
            await self._release(context)
            raise RuntimeError("nested transaction for one session is not supported")
        task_contexts[session_id] = context
        context.renewal_task = asyncio.create_task(self._renew_loop(context))
        try:
            yield
        finally:
            if context.renewal_task is not None:
                context.renewal_task.cancel()
                with suppress(asyncio.CancelledError):
                    await context.renewal_task
            self._contexts.get(task, {}).pop(session_id, None)
            if not self._contexts.get(task):
                self._contexts.pop(task, None)
            await self._release(context)

    def _require_context(self, session_id: str) -> RedisTransactionContext:
        task = asyncio.current_task()
        context = self._contexts.get(task, {}).get(session_id) if task else None
        if context is None:
            raise RuntimeError("SessionStore operation must run inside transaction(session_id)")
        if context.lock_lost:
            raise SessionStoreError("lock_lost")
        return context

    async def _acquire(self, session_id: str) -> RedisTransactionContext:
        base = self._base(session_id)
        keys = self._data_keys(base)
        owner_token = uuid4()
        started = time.monotonic()
        deadline = started + self._acquire_timeout
        try:
            while True:
                result = await self._eval(
                    _ACQUIRE_LUA,
                    keys,
                    str(owner_token),
                    _SCHEMA_VERSION,
                    str(self._lease_ms),
                    str(self._session_ttl),
                )
                if int(result[0]) == 1:
                    waited = time.monotonic() - started
                    record_lock_wait("acquired", waited)
                    emit_event(
                        logger,
                        "session_lock_acquired",
                        status="acquired",
                        backend=self.backend_name,
                        lock_wait_ms=round(waited * 1000),
                    )
                    return RedisTransactionContext(
                        session_id=session_id,
                        base=base,
                        owner_token=owner_token,
                        fencing_token=int(result[1]),
                        lock_value=str(result[2]),
                    )
                if str(result[1]) == "data_invalid":
                    raise SessionStoreError("data_invalid")
                if time.monotonic() >= deadline:
                    waited = time.monotonic() - started
                    record_lock_wait("timeout", waited)
                    emit_event(
                        logger,
                        "session_lock_timeout",
                        status="error",
                        failure_code="lock_timeout",
                        backend=self.backend_name,
                        lock_wait_ms=round(waited * 1000),
                    )
                    raise SessionStoreError("lock_timeout")
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            record_lock_wait("cancelled", time.monotonic() - started)
            raise

    async def _renew_loop(self, context: RedisTransactionContext) -> None:
        while True:
            await asyncio.sleep(self._renew_interval)
            try:
                result = await self._eval(
                    _RENEW_LUA,
                    self._data_keys(context.base),
                    context.lock_value,
                    str(self._lease_ms),
                    str(self._session_ttl),
                )
            except SessionStoreError:
                context.lock_lost = True
                return
            if int(result[0]) != 1:
                context.lock_lost = True
                return

    async def _release(self, context: RedisTransactionContext) -> None:
        try:
            await self._redis.eval(
                _RELEASE_LUA,
                1,
                self._keys_from_base(context.base)["lock"],
                context.lock_value,
            )
        except (OSError, RedisError):
            # The caller's outcome already carries the unavailable/lock-lost failure.
            return

    async def _eval(self, script: str, keys: list[str], *args: str) -> list[Any]:
        try:
            result = await self._redis.eval(script, len(keys), *keys, *args)
        except ResponseError as exc:
            raise SessionStoreError("data_invalid") from exc
        except (OSError, RedisError) as exc:
            raise SessionStoreError("unavailable") from exc
        if not isinstance(result, list):
            raise SessionStoreError("data_invalid")
        return result

    async def _read_request_record(
        self,
        context: RedisTransactionContext,
        request_id: UUID,
        request_key: str,
    ) -> tuple[str, RequestRecord] | None:
        try:
            raw = await self._redis.hget(
                self._keys_from_base(context.base)["requests"], request_key
            )
        except (OSError, RedisError) as exc:
            raise SessionStoreError("unavailable") from exc
        if raw is None:
            return None
        try:
            record = deserialize_request_record(str(raw))
        except ValueError as exc:
            raise SessionStoreError("data_invalid") from exc
        if record.request_id != request_id:
            raise SessionStoreError("data_invalid")
        return str(raw), record

    async def _request_is_completed(
        self,
        context: RedisTransactionContext,
        request_id: UUID,
        request_key: str,
        owner_token: UUID,
    ) -> bool:
        try:
            existing = await self._read_request_record(context, request_id, request_key)
        except SessionStoreError:
            return False
        if existing is None:
            return False
        record = existing[1]
        return record.status == "completed" and record.owner_token == owner_token

    def _raise_write_failure(self, result: list[Any]) -> None:
        if not result or int(result[0]) == 1:
            return
        code = str(result[1]) if len(result) > 1 else "data_invalid"
        if code == "lock_lost":
            raise SessionStoreError("lock_lost")
        raise SessionStoreError("data_invalid")

    def _base(self, session_id: str) -> str:
        return f"{self._key_prefix}:session:{self.session_key_hash(session_id)}"

    @staticmethod
    def session_key_hash(session_id: str) -> str:
        return hashlib.sha256(f"dotamind:session:v1:{session_id}".encode()).hexdigest()

    @staticmethod
    def request_key_hash(request_id: UUID) -> str:
        return hashlib.sha256(f"dotamind:request:v1:{request_id}".encode()).hexdigest()

    def _keys(self, session_id: str) -> dict[str, str]:
        return self._keys_from_base(self._base(session_id))

    @staticmethod
    def _keys_from_base(base: str) -> dict[str, str]:
        return {
            "meta": f"{base}:meta",
            "turns": f"{base}:turns",
            "requests": f"{base}:requests",
            "request_gc": f"{base}:request_gc",
            "lock": f"{base}:lock",
        }

    def _data_keys(self, base: str) -> list[str]:
        keys = self._keys_from_base(base)
        return [keys["lock"], keys["meta"], keys["turns"], keys["requests"], keys["request_gc"]]
