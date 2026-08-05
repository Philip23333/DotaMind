"""Bridge synchronous Graph stream publishers to an async Run Event Bus."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from app.agentic.runtime.streaming import (
    PlanStreamEvent,
    bind_stream_event_publisher,
    publish_stream_event,
    reset_stream_event_publisher,
)
from app.application.run_event_bus import RunEventBus, RunEventBusError
from app.observability import record_chat_run_event, record_chat_run_event_bus_error


class RunEventPump:
    """Queue Graph events and persist them without making Graph nodes async."""

    def __init__(
        self,
        *,
        bus: RunEventBus,
        run_id: UUID,
        session_id: UUID,
        max_queue_size: int = 1024,
    ) -> None:
        self._bus = bus
        self._run_id = run_id
        self._session_id = session_id
        self._queue: asyncio.Queue[PlanStreamEvent | None] = asyncio.Queue(
            maxsize=max_queue_size
        )
        self._task: asyncio.Task[None] | None = None
        self._failure: RunEventBusError | None = None
        self._last_sequence = 0

    @property
    def last_sequence(self) -> int:
        return self._last_sequence

    @property
    def failure(self) -> RunEventBusError | None:
        return self._failure

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("event pump already started")
        self._task = asyncio.create_task(self._run(), name=f"run-event-pump:{self._run_id}")

    def publish(self, event: PlanStreamEvent) -> None:
        if self._task is None:
            raise RuntimeError("event pump is not started")
        if self._failure is not None:
            raise self._failure
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull as exc:
            self._failure = RunEventBusError("queue_full")
            raise self._failure from exc

    async def flush(self) -> None:
        if self._task is None:
            raise RuntimeError("event pump is not started")
        await self._queue.join()
        if self._failure is not None:
            raise self._failure

    async def close(self) -> None:
        if self._task is None:
            return
        try:
            await self.flush()
        finally:
            await self._queue.put(None)
            await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                if event is None:
                    return
                stored = await self._bus.append(
                    run_id=self._run_id,
                    session_id=self._session_id,
                    event=event,
                )
                self._last_sequence = stored.sequence
                record_chat_run_event("published")
            except RunEventBusError as exc:
                self._failure = exc
                record_chat_run_event_bus_error("publish")
            finally:
                self._queue.task_done()


@asynccontextmanager
async def bind_run_event_pump(
    *,
    bus: RunEventBus,
    run_id: UUID,
    session_id: UUID,
) -> AsyncIterator[RunEventPump]:
    """Bind a Run-scoped publisher for one Graph execution."""

    pump = RunEventPump(bus=bus, run_id=run_id, session_id=session_id)
    await pump.start()
    token = bind_stream_event_publisher(pump.publish)
    try:
        yield pump
    finally:
        reset_stream_event_publisher(token)
        await pump.close()


__all__ = ["RunEventPump", "bind_run_event_pump", "publish_stream_event"]
