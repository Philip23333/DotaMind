from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from app.vnext.agent.events import (
    AgentCancelled,
    AgentCompleted,
    AgentEvent,
    AgentFailed,
    AgentStarted,
    AnswerAttemptFailed,
    AnswerAttemptStarted,
    AnswerStageStarted,
    ModelRequested,
    ModelResponded,
    TextDelta,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.llm.protocol import (
    FinalMessage,
    ModelRequest,
    ModelResponse,
    ModelTextDelta,
    UserMessage,
)
from app.vnext.product.run_state import (
    ProductRunState,
    ProductRunStateProjector,
    ToolActivity,
)
from app.vnext.product.runtime_projection import (
    apply_runtime_event,
    iter_runtime_states,
)
from app.vnext.tools import ToolRegistry

_SAFE_FAILURE_MESSAGE = "本次回答未能完成，请重试。"


def _projector() -> ProductRunStateProjector:
    return ProductRunStateProjector(uuid4(), "assistant-message-1")


def _start_attempt(
    projector: ProductRunStateProjector,
    attempt_id: str = "primary-1",
    kind: str = "primary",
) -> None:
    apply_runtime_event(projector, AnswerStageStarted())
    apply_runtime_event(
        projector,
        AnswerAttemptStarted(attempt_id=attempt_id, answer_kind=kind),  # type: ignore[arg-type]
    )


def _runtime(model: object) -> AgentRuntime:
    return AgentRuntime(
        model,  # type: ignore[arg-type]
        ToolRegistry(),
        limits=AgentLimits(
            application_max_output_tokens=4096, deadline_seconds=3, answer_timeout_seconds=3
        ),
    )


async def _events(items: list[AgentEvent]) -> AsyncIterator[AgentEvent]:
    for item in items:
        yield item


async def _collect_states(
    events: AsyncIterator[AgentEvent],
) -> list[ProductRunState]:
    states: list[ProductRunState] = []
    async for state in iter_runtime_states(
        events,
        request_id=uuid4(),
        assistant_message_id="assistant-message-1",
    ):
        states.append(state)
    return states


def test_mapping_projects_tool_lifecycle_without_exposing_raw_error_text() -> None:
    projector = _projector()
    assert not apply_runtime_event(projector, AgentStarted())
    assert not apply_runtime_event(
        projector,
        ModelRequested(step=1, message_count=2, tool_count=1),
    )
    assert apply_runtime_event(
        projector,
        ToolStarted(tool_call_id="call-1", tool_name="esports.match.search"),
    )
    assert apply_runtime_event(
        projector,
        ToolCompleted(
            tool_call_id="call-1",
            tool_name="esports.match.search",
            duration=0.25,
        ),
    )
    assert apply_runtime_event(
        projector,
        ToolStarted(tool_call_id="call-2", tool_name="esports.team.search"),
    )
    assert apply_runtime_event(
        projector,
        ToolFailed(
            tool_call_id="call-2",
            tool_name="esports.team.search",
            duration=0.5,
            error_code="provider_unavailable",
            error_message="sensitive provider response and token=secret",
        ),
    )
    assert not apply_runtime_event(
        projector,
        ModelResponded(step=1, has_tool_calls=True, duration=0.75),
    )

    state = projector.snapshot()
    tools = [item for item in state.activity if isinstance(item, ToolActivity)]
    assert [(item.id, item.status) for item in tools] == [
        ("call-1", "completed"),
        ("call-2", "failed"),
    ]
    assert [item.error_code for item in tools] == [None, "provider_unavailable"]
    assert state.status == "running"
    assert "sensitive provider response" not in state.model_dump_json()


def test_answer_attempt_failure_waits_for_fallback_and_stale_events_are_ignored() -> None:
    projector = _projector()
    _start_attempt(projector)
    assert apply_runtime_event(
        projector,
        TextDelta(text="partial primary", attempt_id="primary-1"),
    )
    before_attempt_failure = projector.snapshot()
    assert not apply_runtime_event(
        projector,
        AnswerAttemptFailed(attempt_id="primary-1", error_code="provider_error"),
    )
    assert projector.snapshot() == before_attempt_failure

    assert apply_runtime_event(
        projector,
        AnswerAttemptStarted(attempt_id="degraded-1", answer_kind="degraded"),
    )
    reset = projector.snapshot()
    assert reset.answer.text == ""
    assert reset.answer.kind == "degraded"
    assert not apply_runtime_event(
        projector,
        TextDelta(text="late primary", attempt_id="primary-1"),
    )
    assert not apply_runtime_event(
        projector,
        AgentCompleted(
            final=FinalMessage(content="late primary final"),
            duration=1,
            attempt_id="primary-1",
        ),
    )
    assert apply_runtime_event(
        projector,
        TextDelta(text="degraded fragment", attempt_id="degraded-1"),
    )
    assert apply_runtime_event(
        projector,
        AgentCompleted(
            final=FinalMessage(content="canonical degraded answer"),
            duration=2,
            attempt_id="degraded-1",
        ),
    )

    completed = projector.snapshot()
    assert completed.status == "completed"
    assert completed.answer.text == "canonical degraded answer"
    assert completed.answer.status == "ready"
    assert completed.persistence == "pending"


def test_deterministic_fallback_can_complete_without_text_deltas() -> None:
    projector = _projector()
    _start_attempt(projector)
    apply_runtime_event(projector, TextDelta(text="discard this", attempt_id="primary-1"))
    apply_runtime_event(
        projector,
        AnswerAttemptStarted(attempt_id="deterministic-1", answer_kind="deterministic"),
    )

    assert apply_runtime_event(
        projector,
        AgentCompleted(
            final=FinalMessage(content="deterministic answer"),
            duration=0,
            attempt_id="deterministic-1",
        ),
    )
    state = projector.snapshot()
    assert state.status == "completed"
    assert state.answer.kind == "deterministic"
    assert state.answer.text == "deterministic answer"
    assert state.persistence == "pending"


def test_dual_truncated_attempt_projection_keeps_only_deterministic_delivery() -> None:
    projector = _projector()
    _start_attempt(projector)
    assert apply_runtime_event(
        projector,
        TextDelta(text="partial primary", attempt_id="primary-1"),
    )
    assert not apply_runtime_event(
        projector,
        AnswerAttemptFailed(
            attempt_id="primary-1",
            error_code="answer_output_truncated",
        ),
    )
    assert apply_runtime_event(
        projector,
        AnswerAttemptStarted(attempt_id="degraded-1", answer_kind="degraded"),
    )
    assert projector.snapshot().answer.text == ""
    assert apply_runtime_event(
        projector,
        TextDelta(text="partial degraded", attempt_id="degraded-1"),
    )
    assert not apply_runtime_event(
        projector,
        AnswerAttemptFailed(
            attempt_id="degraded-1",
            error_code="answer_output_truncated",
        ),
    )
    assert apply_runtime_event(
        projector,
        AnswerAttemptStarted(attempt_id="deterministic-1", answer_kind="deterministic"),
    )
    final_text = (
        "Execution stopped because the model repeatedly submitted invalid or truncated "
        "tool-call batches.\n\n1 of 2 planned parts were completed. "
        "The remaining parts were not completed, so I won't infer or fill them in."
    )
    assert apply_runtime_event(
        projector,
        AgentCompleted(
            final=FinalMessage(content=final_text),
            duration=0,
            attempt_id="deterministic-1",
        ),
    )

    state = projector.snapshot()
    assert state.status == "completed"
    assert state.answer.kind == "deterministic"
    assert state.answer.text == final_text
    assert "partial primary" not in state.answer.text
    assert "partial degraded" not in state.answer.text
    assert state.persistence == "pending"


@pytest.mark.parametrize(
    ("event", "message"),
    [
        (TextDelta(text="missing identity"), "text delta requires an answer attempt ID"),
        (
            AgentCompleted(final=FinalMessage(content="missing identity"), duration=0),
            "completion requires an answer attempt ID",
        ),
        (
            TextDelta(text="no attempt", attempt_id="attempt-1"),
            "text delta arrived before an answer attempt started",
        ),
        (
            AgentCompleted(
                final=FinalMessage(content="no attempt"),
                duration=0,
                attempt_id="attempt-1",
            ),
            "completion arrived before an answer attempt started",
        ),
    ],
)
def test_answer_text_and_completion_require_an_active_attempt(
    event: AgentEvent,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        apply_runtime_event(_projector(), event)


def test_runtime_failure_uses_safe_product_message_and_preserves_error_code() -> None:
    projector = _projector()

    assert apply_runtime_event(
        projector,
        AgentFailed(
            duration=1,
            error_code="model_provider_error",
            error_message="raw provider error token=secret traceback=private",
            details={"raw": "secret"},
        ),
    )

    state = projector.snapshot()
    assert state.status == "failed"
    assert state.error is not None
    assert state.error.code == "model_provider_error"
    assert state.error.message == _SAFE_FAILURE_MESSAGE
    assert "secret" not in state.model_dump_json()


def test_incomplete_upstream_stream_becomes_safe_terminal_failure() -> None:
    states = asyncio.run(
        _collect_states(
            _events(
                [
                    AnswerStageStarted(),
                    AnswerAttemptStarted(attempt_id="primary-1", answer_kind="primary"),
                    TextDelta(text="partial answer", attempt_id="primary-1"),
                ]
            )
        )
    )

    final = states[-1]
    assert final.status == "failed"
    assert final.error is not None
    assert final.error.scope == "execution"
    assert final.error.code == "agent_stream_incomplete"
    assert final.error.message == _SAFE_FAILURE_MESSAGE
    assert final.answer.status == "interrupted"
    assert final.answer.text == "partial answer"


def test_upstream_exception_becomes_safe_terminal_failure() -> None:
    async def failing_events() -> AsyncIterator[AgentEvent]:
        yield AnswerStageStarted()
        yield AnswerAttemptStarted(attempt_id="primary-1", answer_kind="primary")
        yield TextDelta(text="partial answer", attempt_id="primary-1")
        raise RuntimeError("provider token=secret private stack")

    states = asyncio.run(_collect_states(failing_events()))

    final = states[-1]
    assert final.status == "failed"
    assert final.error is not None
    assert final.error.code == "agent_runtime_error"
    assert final.error.message == _SAFE_FAILURE_MESSAGE
    assert final.answer.status == "interrupted"
    assert final.answer.text == "partial answer"
    assert "secret" not in final.model_dump_json()


def test_runtime_first_fragment_projects_before_model_terminal_response() -> None:
    async def exercise() -> None:
        release_terminal = asyncio.Event()
        terminal_produced = asyncio.Event()

        class _GatedModel:
            def stream(self, request: ModelRequest):
                async def generate():
                    if request.step == 1:
                        yield ModelResponse.from_final("execution")
                        return
                    yield ModelTextDelta(text="first ")
                    await release_terminal.wait()
                    yield ModelTextDelta(text="answer")
                    terminal_produced.set()
                    yield ModelResponse.from_final("first answer")

                return generate()

        state_stream = iter_runtime_states(
            _runtime(_GatedModel()).run_stream([UserMessage(content="hello")]),
            request_id=uuid4(),
            assistant_message_id="assistant-live",
        )
        try:
            initial = await asyncio.wait_for(anext(state_stream), timeout=1)
            answer_stage = await asyncio.wait_for(anext(state_stream), timeout=1)
            attempt = await asyncio.wait_for(anext(state_stream), timeout=1)
            streaming = await asyncio.wait_for(anext(state_stream), timeout=1)

            assert initial.stage == "execution"
            assert answer_stage.stage == "answer"
            assert attempt.answer.attempt_id is not None
            assert streaming.answer.status == "streaming"
            assert streaming.answer.text == "first "
            assert not terminal_produced.is_set()
            assert streaming.status == "running"

            release_terminal.set()
            later_states = [state async for state in state_stream]
            completed = later_states[-1]
            assert completed.status == "completed"
            assert completed.answer.status == "ready"
            assert completed.answer.text == "first answer"
            assert completed.persistence == "pending"
        finally:
            release_terminal.set()
            await state_stream.aclose()

    asyncio.run(exercise())


def test_runtime_fallback_snapshot_clears_primary_text_before_degraded_text() -> None:
    class _FallbackModel:
        def stream(self, request: ModelRequest):
            async def generate():
                if request.step == 1:
                    yield ModelResponse.from_final("execution")
                elif request.step == 2:
                    yield ModelTextDelta(text="partial primary")
                    raise RuntimeError("primary failed")
                else:
                    yield ModelTextDelta(text="degraded answer")
                    yield ModelResponse.from_final("canonical degraded answer")

            return generate()

    states = asyncio.run(
        _collect_states(_runtime(_FallbackModel()).run_stream([UserMessage(content="hello")]))
    )

    primary_partial = next(state for state in states if state.answer.text == "partial primary")
    degraded_reset = next(
        state for state in states if state.answer.kind == "degraded" and not state.answer.text
    )
    degraded_partial = next(state for state in states if state.answer.text == "degraded answer")
    completed = states[-1]
    assert primary_partial.answer.kind == "primary"
    assert degraded_reset.answer.status == "pending"
    assert degraded_partial.answer.kind == "degraded"
    assert completed.status == "completed"
    assert completed.answer.text == "canonical degraded answer"


def test_explicit_state_stream_close_closes_runtime_provider_without_fallback() -> None:
    async def exercise() -> None:
        closed_steps: list[int] = []

        class _ClosableModel:
            def stream(self, request: ModelRequest):
                async def generate():
                    try:
                        if request.step == 1:
                            yield ModelResponse.from_final("execution")
                            return
                        yield ModelTextDelta(text="first answer fragment")
                        await asyncio.Future()
                    finally:
                        closed_steps.append(request.step)

                return generate()

        model = _ClosableModel()
        state_stream = iter_runtime_states(
            _runtime(model).run_stream([UserMessage(content="hello")]),
            request_id=uuid4(),
            assistant_message_id="assistant-cancelled",
        )
        try:
            await asyncio.wait_for(anext(state_stream), timeout=1)
            await asyncio.wait_for(anext(state_stream), timeout=1)
            await asyncio.wait_for(anext(state_stream), timeout=1)
            answer = await asyncio.wait_for(anext(state_stream), timeout=1)
            assert answer.answer.status == "streaming"
            assert answer.answer.text == "first answer fragment"

            await state_stream.aclose()

            assert len(closed_steps) == 2
            assert not [
                task
                for task in asyncio.all_tasks()
                if task is not asyncio.current_task() and not task.done()
            ]
        finally:
            await state_stream.aclose()

    asyncio.run(exercise())


def test_cancelling_state_consumer_propagates_and_closes_runtime_provider() -> None:
    async def exercise() -> None:
        closed_steps: list[int] = []
        streaming_received = asyncio.Event()

        class _ClosableModel:
            def stream(self, request: ModelRequest):
                async def generate():
                    try:
                        if request.step == 1:
                            yield ModelResponse.from_final("execution")
                            return
                        yield ModelTextDelta(text="partial")
                        await asyncio.Future()
                    finally:
                        closed_steps.append(request.step)

                return generate()

        state_stream = iter_runtime_states(
            _runtime(_ClosableModel()).run_stream([UserMessage(content="hello")]),
            request_id=uuid4(),
            assistant_message_id="assistant-cancelled",
        )

        async def consume_until_next_state() -> None:
            while True:
                state = await anext(state_stream)
                if state.answer.status == "streaming":
                    streaming_received.set()
                    await anext(state_stream)

        task = asyncio.create_task(consume_until_next_state())
        await asyncio.wait_for(streaming_received.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        await state_stream.aclose()

        assert len(closed_steps) == 2
        assert not [
            pending
            for pending in asyncio.all_tasks()
            if pending is not asyncio.current_task() and not pending.done()
        ]

    asyncio.run(exercise())


def test_interleaved_state_streams_are_isolated_and_snapshots_are_independent() -> None:
    async def exercise() -> None:
        first_events = _events(
            [
                AnswerStageStarted(),
                AnswerAttemptStarted(attempt_id="first-attempt", answer_kind="primary"),
                TextDelta(text="first", attempt_id="first-attempt"),
                TextDelta(text=" update", attempt_id="first-attempt"),
            ]
        )
        second_events = _events(
            [
                AnswerStageStarted(),
                AnswerAttemptStarted(attempt_id="second-attempt", answer_kind="primary"),
                TextDelta(text="second", attempt_id="second-attempt"),
            ]
        )
        first = iter_runtime_states(
            first_events,
            request_id=uuid4(),
            assistant_message_id="assistant-first",
        )
        second = iter_runtime_states(
            second_events,
            request_id=uuid4(),
            assistant_message_id="assistant-second",
        )
        try:
            first_initial, second_initial = await anext(first), await anext(second)
            first_stage, second_stage = await anext(first), await anext(second)
            first_attempt, second_attempt = await anext(first), await anext(second)
            first_text, second_text = await anext(first), await anext(second)
            first_text.answer.text = "mutated outside the projector"
            first_update = await anext(first)

            assert first_initial.request_id != second_initial.request_id
            assert first_stage.assistant_message_id == "assistant-first"
            assert second_stage.assistant_message_id == "assistant-second"
            assert first_attempt.answer.attempt_id == "first-attempt"
            assert second_attempt.answer.attempt_id == "second-attempt"
            assert second_text.answer.text == "second"
            assert first_update.answer.text == "first update"
        finally:
            await first.aclose()
            await second.aclose()

    asyncio.run(exercise())


def test_terminal_snapshot_closes_upstream_before_any_late_event_is_consumed() -> None:
    async def exercise() -> None:
        closed = asyncio.Event()
        late_event_consumed = False

        async def source() -> AsyncIterator[AgentEvent]:
            nonlocal late_event_consumed
            try:
                yield AnswerStageStarted()
                yield AnswerAttemptStarted(attempt_id="primary-1", answer_kind="primary")
                yield AgentCompleted(
                    final=FinalMessage(content="canonical answer"),
                    duration=1,
                    attempt_id="primary-1",
                )
                late_event_consumed = True
                yield TextDelta(text="too late", attempt_id="primary-1")
            finally:
                closed.set()

        states = iter_runtime_states(
            source(),
            request_id=uuid4(),
            assistant_message_id="assistant-terminal",
        )
        collected = [state async for state in states]

        assert collected[-1].status == "completed"
        assert collected[-1].answer.text == "canonical answer"
        assert closed.is_set()
        assert not late_event_consumed

    asyncio.run(exercise())


def test_cancel_event_interrupts_partial_answer_without_starting_persistence() -> None:
    states = asyncio.run(
        _collect_states(
            _events(
                [
                    AnswerStageStarted(),
                    AnswerAttemptStarted(attempt_id="primary-1", answer_kind="primary"),
                    TextDelta(text="partial", attempt_id="primary-1"),
                    AgentCancelled(error_message="cancelled by user"),
                ]
            )
        )
    )

    cancelled = states[-1]
    assert cancelled.status == "cancelled"
    assert cancelled.answer.status == "interrupted"
    assert cancelled.answer.text == "partial"
    assert cancelled.persistence == "pending"
