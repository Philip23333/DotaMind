from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from app.agentic.runtime.streaming import PhaseStreamEvent
from app.application.redis_run_event_bus import RedisRunEventBus
from app.application.run_event_bus import RunEventBusError, StoredRunEvent
from app.application.run_event_pump import bind_run_event_pump


def test_redis_event_bus_fails_fast_without_an_in_memory_fallback() -> None:
    async def scenario() -> None:
        bus = RedisRunEventBus(redis=BrokenRedis())
        with pytest.raises(RunEventBusError, match="unavailable"):
            await bus.append(
                run_id=uuid4(),
                session_id=uuid4(),
                event=PhaseStreamEvent(phase="planning", attempt_index=0),
            )

    asyncio.run(scenario())


def test_event_pump_completes_after_observer_disappears() -> None:
    async def scenario() -> None:
        bus = RecordingBus()
        async with bind_run_event_pump(
            bus=bus,
            run_id=uuid4(),
            session_id=uuid4(),
        ) as pump:
            # No HTTP subscriber is attached. The detached Run still owns and
            # flushes its event queue.
            from app.agentic.runtime.streaming import publish_stream_event

            publish_stream_event(PhaseStreamEvent(phase="planning", attempt_index=0))
            await pump.flush()
        assert len(bus.events) == 1
        assert bus.events[0].sequence == 1

    asyncio.run(scenario())


class BrokenRedis:
    def register_script(self, script):
        async def execute(**kwargs):
            raise RedisError("redis down")

        return execute


class RecordingBus:
    def __init__(self) -> None:
        self.events: list[StoredRunEvent] = []

    async def append(self, *, run_id, session_id, event) -> StoredRunEvent:
        stored = StoredRunEvent(
            run_id=run_id,
            session_id=session_id,
            sequence=len(self.events) + 1,
            event=event,
        )
        self.events.append(stored)
        return stored
