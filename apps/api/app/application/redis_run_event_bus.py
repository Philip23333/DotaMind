"""Redis Stream implementation for replayable chat Run events."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.agentic.runtime.streaming import PlanStreamEvent, StatusStreamEvent
from app.application.run_event_bus import (
    RunCancelNotification,
    RunEventBusError,
    StoredRunEvent,
)

_APPEND_LUA = """
local sequence = redis.call('INCR', KEYS[2])
redis.call(
  'XADD', KEYS[1], tostring(sequence) .. '-0',
  'event', ARGV[1],
  'run_id', ARGV[2],
  'session_id', ARGV[3],
  'sequence', tostring(sequence)
)
redis.call('EXPIRE', KEYS[1], ARGV[4])
redis.call('EXPIRE', KEYS[2], ARGV[4])
return sequence
"""


@dataclass(frozen=True)
class _RedisRunKeys:
    stream: str
    sequence: str


class RedisRunEventBus:
    """One Redis primary stores short-lived per-Run events and cancel notices."""

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        redis: Redis | None = None,
        event_ttl_seconds: int = 86400,
        key_prefix: str = "dotamind:v1",
        cancel_channel: str | None = None,
    ) -> None:
        if redis is None and redis_url is None:
            raise ValueError("redis_url or redis client is required")
        self._redis = redis or Redis.from_url(redis_url, decode_responses=True)
        self._owns_redis = redis is None
        self._event_ttl_seconds = event_ttl_seconds
        self._key_prefix = key_prefix.rstrip(":")
        self._cancel_channel = cancel_channel or f"{self._key_prefix}:run-cancel"
        self._append_script = self._redis.register_script(_APPEND_LUA)

    async def ping(self) -> None:
        try:
            await self._redis.ping()
        except RedisError as exc:
            raise RunEventBusError("unavailable") from exc

    async def append(
        self, *, run_id: UUID, session_id: UUID, event: PlanStreamEvent
    ) -> StoredRunEvent:
        payload = json.dumps(
            event.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        keys = self._keys(run_id)
        try:
            sequence = int(
                await self._append_script(
                    keys=[keys.stream, keys.sequence],
                    args=[
                        payload,
                        str(run_id),
                        str(session_id),
                        str(self._event_ttl_seconds),
                    ],
                )
            )
        except RedisError as exc:
            raise RunEventBusError("unavailable") from exc
        return StoredRunEvent(
            run_id=run_id,
            session_id=session_id,
            sequence=sequence,
            event=event,
        )

    async def read_after(
        self, *, run_id: UUID, session_id: UUID, after: int
    ) -> list[StoredRunEvent]:
        try:
            result = await self._redis.xread(
                {self._keys(run_id).stream: f"{after}-0"},
                count=100,
            )
        except RedisError as exc:
            raise RunEventBusError("unavailable") from exc
        return self._decode_entries(result, run_id=run_id, session_id=session_id)

    async def wait_after(
        self, *, run_id: UUID, session_id: UUID, after: int, timeout_seconds: int
    ) -> list[StoredRunEvent]:
        try:
            result = await self._redis.xread(
                {self._keys(run_id).stream: f"{after}-0"},
                count=100,
                block=max(timeout_seconds, 1) * 1000,
            )
        except RedisError as exc:
            raise RunEventBusError("unavailable") from exc
        return self._decode_entries(result, run_id=run_id, session_id=session_id)

    async def publish_cancel(
        self, *, run_id: UUID, target_worker_id: str | None
    ) -> None:
        message = json.dumps(
            {"run_id": str(run_id), "target_worker_id": target_worker_id},
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            await self._redis.publish(self._cancel_channel, message)
        except RedisError as exc:
            raise RunEventBusError("unavailable") from exc

    async def subscribe_cancellations(self) -> AsyncIterator[RunCancelNotification]:
        pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        try:
            await pubsub.subscribe(self._cancel_channel)
            while True:
                message = await pubsub.get_message(timeout=1.0)
                if message is None:
                    await asyncio.sleep(0.05)
                    continue
                try:
                    data = json.loads(message["data"])
                    yield RunCancelNotification(
                        run_id=UUID(data["run_id"]),
                        target_worker_id=data.get("target_worker_id"),
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise RunEventBusError("data_invalid") from exc
        except RedisError as exc:
            raise RunEventBusError("unavailable") from exc
        finally:
            await pubsub.unsubscribe(self._cancel_channel)
            await pubsub.aclose()

    async def aclose(self) -> None:
        if self._owns_redis:
            await self._redis.aclose()

    def stream_key(self, run_id: UUID) -> str:
        return self._keys(run_id).stream

    def sequence_key(self, run_id: UUID) -> str:
        return self._keys(run_id).sequence

    def _keys(self, run_id: UUID) -> _RedisRunKeys:
        digest = hashlib.sha256(
            f"dotamind:chat-run:v1:{run_id}".encode()
        ).hexdigest()
        base = f"{self._key_prefix}:run:{digest}"
        return _RedisRunKeys(stream=f"{base}:events", sequence=f"{base}:sequence")

    @staticmethod
    def _decode_entries(
        result: list, *, run_id: UUID, session_id: UUID
    ) -> list[StoredRunEvent]:
        if not result:
            return []
        events: list[StoredRunEvent] = []
        try:
            for stream_record in result:
                if not isinstance(stream_record, (list, tuple)) or len(stream_record) != 2:
                    raise ValueError("invalid redis stream record")
                _, entries = stream_record
                for entry in entries:
                    if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                        raise ValueError("invalid redis stream entry")
                    _, fields = entry
                    if isinstance(fields, list):
                        fields = dict(zip(fields[::2], fields[1::2], strict=False))
                    sequence = int(fields["sequence"])
                    event_payload = json.loads(fields["event"])
                    parsed_event = _parse_event(event_payload)
                    events.append(
                        StoredRunEvent(
                            run_id=run_id,
                            session_id=session_id,
                            sequence=sequence,
                            event=parsed_event,
                        )
                    )
        except RunEventBusError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RunEventBusError("data_invalid") from exc
        return events


def _parse_event(payload: dict) -> PlanStreamEvent:
    event_type = payload.get("type")
    if event_type == "status":
        return StatusStreamEvent.model_validate(payload)
    from app.agentic.runtime.streaming import (
        AnswerDeltaStreamEvent,
        CheckpointStreamEvent,
        ErrorStreamEvent,
        ObserverStreamEvent,
        PhaseStreamEvent,
        ResultStreamEvent,
        ToolStreamEvent,
    )

    event_types = {
        "answer_delta": AnswerDeltaStreamEvent,
        "checkpoint": CheckpointStreamEvent,
        "error": ErrorStreamEvent,
        "observer": ObserverStreamEvent,
        "phase": PhaseStreamEvent,
        "result": ResultStreamEvent,
        "tool": ToolStreamEvent,
    }
    event_model = event_types.get(event_type)
    if event_model is None:
        raise RunEventBusError("data_invalid")
    return event_model.model_validate(payload)
