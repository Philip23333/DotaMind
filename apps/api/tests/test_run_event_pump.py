"""Unit coverage for the synchronous-to-async Run event bridge."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from app.agentic.runtime.streaming import PhaseStreamEvent, publish_stream_event
from app.application.run_event_bus import RunEventBusError, StoredRunEvent
from app.application.run_event_pump import bind_run_event_pump


@dataclass
class FakeRunEventBus:
    events: list[StoredRunEvent] = field(default_factory=list)
    failure: RunEventBusError | None = None

    async def append(self, *, run_id: UUID, session_id: UUID, event):
        if self.failure is not None:
            raise self.failure
        stored = StoredRunEvent(
            run_id=run_id,
            session_id=session_id,
            sequence=len(self.events) + 1,
            event=event,
        )
        self.events.append(stored)
        return stored


def test_run_event_pump_flushes_graph_events_in_order() -> None:
    async def scenario() -> None:
        bus = FakeRunEventBus()
        run_id, session_id = uuid4(), uuid4()
        async with bind_run_event_pump(
            bus=bus,
            run_id=run_id,
            session_id=session_id,
        ) as pump:
            publish_stream_event(PhaseStreamEvent(phase="planning", attempt_index=0))
            publish_stream_event(PhaseStreamEvent(phase="answering", attempt_index=0))
            await pump.flush()
            assert pump.last_sequence == 2

        assert [item.sequence for item in bus.events] == [1, 2]
        assert [item.event.phase for item in bus.events] == ["planning", "answering"]

    asyncio.run(scenario())


def test_run_event_pump_surfaces_event_bus_failure() -> None:
    async def scenario() -> None:
        bus = FakeRunEventBus(failure=RunEventBusError("unavailable"))
        with pytest.raises(RunEventBusError, match="unavailable"):
            async with bind_run_event_pump(
                bus=bus,
                run_id=uuid4(),
                session_id=uuid4(),
            ):
                publish_stream_event(PhaseStreamEvent(phase="planning", attempt_index=0))
                await asyncio.sleep(0)

    asyncio.run(scenario())
