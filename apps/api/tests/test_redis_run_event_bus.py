"""Redis integration coverage for the V3.3-2 Run Event Bus."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.agentic.runtime.streaming import PhaseStreamEvent
from app.application.redis_run_event_bus import RedisRunEventBus
from app.application.run_event_bus import RunEventBusError

pytestmark = pytest.mark.skipif(
    not os.getenv("DOTAMIND_TEST_REDIS_URL"),
    reason="set DOTAMIND_TEST_REDIS_URL to run Redis integration tests",
)


def test_redis_run_event_bus_sequences_replays_and_cancel_notifications() -> None:
    async def scenario() -> None:
        redis = Redis.from_url(os.environ["DOTAMIND_TEST_REDIS_URL"], decode_responses=True)
        prefix = f"dotamind:test:run-events:{uuid4()}"
        bus = RedisRunEventBus(redis=redis, key_prefix=prefix, event_ttl_seconds=60)
        run_id = uuid4()
        session_id = uuid4()
        try:
            await bus.ping()
            first = await bus.append(
                run_id=run_id,
                session_id=session_id,
                event=PhaseStreamEvent(phase="planning", attempt_index=0),
            )
            second = await bus.append(
                run_id=run_id,
                session_id=session_id,
                event=PhaseStreamEvent(phase="answering", attempt_index=0),
            )
            assert first.sequence == 1
            assert second.sequence == 2
            replayed = await bus.read_after(run_id=run_id, session_id=session_id, after=0)
            assert [item.sequence for item in replayed] == [1, 2]
            tail = await bus.read_after(run_id=run_id, session_id=session_id, after=1)
            assert [item.sequence for item in tail] == [2]
            assert tail[0].event.type == "phase"

            with pytest.raises(RunEventBusError, match="data_invalid"):
                RedisRunEventBus._decode_entries(
                    [[("1-0", {"sequence": "bad", "event": "{}"})]],
                    run_id=run_id,
                    session_id=session_id,
                )
        finally:
            await redis.delete(bus.stream_key(run_id), bus.sequence_key(run_id))
            await bus.aclose()
            await redis.aclose()

    asyncio.run(scenario())
