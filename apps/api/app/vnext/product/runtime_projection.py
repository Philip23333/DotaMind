"""Project Runtime lifecycle events into request-local product run states."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from app.vnext.agent.events import (
    AgentCancelled,
    AgentCompleted,
    AgentEvent,
    AgentFailed,
    AgentStarted,
    AnswerAttemptFailed,
    AnswerAttemptStarted,
    AnswerStageStarted,
    ExecutionCommentary,
    ModelRequested,
    ModelResponded,
    TextDelta,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)
from app.vnext.product.run_state import ProductRunState, ProductRunStateProjector

_SAFE_FAILURE_MESSAGE = "本次回答未能完成，请重试。"


def apply_runtime_event(
    projector: ProductRunStateProjector,
    event: AgentEvent,
) -> bool:
    """Apply one Runtime fact and report whether the product state changed."""

    before = projector.snapshot()

    if isinstance(event, AgentStarted):
        projector.start_execution(event.timestamp)
    elif isinstance(event, (ModelRequested, ModelResponded, AnswerAttemptFailed)):
        pass
    elif isinstance(event, ExecutionCommentary):
        projector.add_commentary(event.step, event.text)
    elif isinstance(event, ToolStarted):
        projector.tool_started(event.tool_call_id, event.tool_name)
    elif isinstance(event, ToolCompleted):
        projector.tool_finished(
            event.tool_call_id,
            duration_seconds=event.duration,
        )
    elif isinstance(event, ToolFailed):
        projector.tool_finished(
            event.tool_call_id,
            duration_seconds=event.duration,
            error_code=event.error_code,
        )
    elif isinstance(event, AnswerStageStarted):
        projector.enter_stage("answer", timestamp=event.timestamp)
    elif isinstance(event, AnswerAttemptStarted):
        projector.start_answer_attempt(event.attempt_id, event.answer_kind)
    elif isinstance(event, TextDelta):
        attempt_id = _require_current_attempt(projector, event.attempt_id, "text delta")
        if attempt_id is None:
            return False
        projector.append_answer_text(attempt_id, event.text)
    elif isinstance(event, AgentCompleted):
        attempt_id = _require_current_attempt(projector, event.attempt_id, "completion")
        if attempt_id is None:
            return False
        projector.complete_answer(attempt_id, event.final.content)
    elif isinstance(event, AgentCancelled):
        projector.cancel(timestamp=event.timestamp)
    elif isinstance(event, AgentFailed):
        projector.fail_execution(
            event.error_code,
            _SAFE_FAILURE_MESSAGE,
            timestamp=event.timestamp,
        )

    return projector.snapshot() != before


def _require_current_attempt(
    projector: ProductRunStateProjector,
    attempt_id: str | None,
    event_name: str,
) -> str | None:
    if attempt_id is None:
        raise ValueError(f"{event_name} requires an answer attempt ID")

    current_attempt_id = projector.snapshot().answer.attempt_id
    if current_attempt_id is None:
        raise ValueError(f"{event_name} arrived before an answer attempt started")
    if attempt_id != current_attempt_id:
        return None
    return attempt_id


async def iter_runtime_states(
    events: AsyncIterator[AgentEvent],
    *,
    request_id: UUID,
    assistant_message_id: str,
) -> AsyncIterator[ProductRunState]:
    """Yield changed product snapshots while consuming one Runtime event stream."""

    projector = ProductRunStateProjector(request_id, assistant_message_id)
    try:
        yield projector.snapshot()
        while True:
            try:
                event = await anext(events)
            except StopAsyncIteration:
                if projector.snapshot().status == "running":
                    projector.fail_execution("agent_stream_incomplete", _SAFE_FAILURE_MESSAGE)
                    await _close_upstream(events)
                    yield projector.snapshot()
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                projector.fail_execution("agent_runtime_error", _SAFE_FAILURE_MESSAGE)
                await _close_upstream(events)
                yield projector.snapshot()
                return

            if not apply_runtime_event(projector, event):
                continue

            state = projector.snapshot()
            if state.status != "running":
                await _close_upstream(events)
                yield state
                return
            yield state
    finally:
        await _close_upstream(events)


async def _close_upstream(events: AsyncIterator[AgentEvent]) -> None:
    close = getattr(events, "aclose", None)
    if callable(close):
        await close()


__all__ = ["apply_runtime_event", "iter_runtime_states"]
