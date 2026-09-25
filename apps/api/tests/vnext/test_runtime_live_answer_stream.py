from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.vnext.agent.errors import AgentCancelledError
from app.vnext.agent.events import (
    AgentCancelled,
    AgentCompleted,
    AnswerAttemptFailed,
    AnswerAttemptStarted,
    TextDelta,
)
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime, CancellationToken
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelRequest,
    ModelResponse,
    ModelTextDelta,
    ToolCall,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools import ToolRegistry
from tests.vnext.fakes import ScriptedModelClient


def _runtime(model: object, **kwargs: object) -> AgentRuntime:
    return AgentRuntime(
        model,  # type: ignore[arg-type]
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=3, answer_timeout_seconds=3),
        **kwargs,
    )


def test_primary_first_delta_arrives_before_terminal_model_response() -> None:
    async def exercise() -> None:
        release_terminal = asyncio.Event()
        first_delta_received = asyncio.Event()
        terminal_produced = asyncio.Event()
        events: list[object] = []

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

        runtime = _runtime(_GatedModel())
        stream = runtime.run_stream([UserMessage(content="hello")])

        async def consume() -> None:
            async for event in stream:
                events.append(event)
                if isinstance(event, TextDelta):
                    first_delta_received.set()

        task = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(first_delta_received.wait(), timeout=1)
            assert not terminal_produced.is_set()
            assert not any(isinstance(event, AgentCompleted) for event in events)
            assert [event.text for event in events if isinstance(event, TextDelta)] == ["first "]
        finally:
            release_terminal.set()
            await asyncio.wait_for(task, timeout=1)

        assert terminal_produced.is_set()
        assert [event.text for event in events if isinstance(event, TextDelta)] == [
            "first ",
            "answer",
        ]
        started = next(event for event in events if isinstance(event, AnswerAttemptStarted))
        deltas = [event for event in events if isinstance(event, TextDelta)]
        completed = next(event for event in events if isinstance(event, AgentCompleted))
        assert all(event.attempt_id == started.attempt_id for event in deltas)
        assert completed.attempt_id == started.attempt_id
        assert completed.final.content == "first answer"

    asyncio.run(exercise())


def test_degraded_first_delta_arrives_before_its_terminal_response() -> None:
    async def exercise() -> None:
        release_terminal = asyncio.Event()
        degraded_delta_received = asyncio.Event()
        terminal_produced = asyncio.Event()
        events: list[object] = []

        class _GatedFallbackModel:
            def stream(self, request: ModelRequest):
                async def generate():
                    if request.step == 1:
                        yield ModelResponse.from_final("execution")
                        return
                    if request.step == 2:
                        raise RuntimeError("primary unavailable")
                    yield ModelTextDelta(text="degraded ")
                    await release_terminal.wait()
                    terminal_produced.set()
                    yield ModelResponse.from_final("degraded answer")

                return generate()

        runtime = _runtime(_GatedFallbackModel())
        task = asyncio.create_task(
            _consume_stream(
                runtime.run_stream([UserMessage(content="hello")]),
                events,
                on_delta=degraded_delta_received,
            )
        )
        try:
            await asyncio.wait_for(degraded_delta_received.wait(), timeout=1)
            assert not terminal_produced.is_set()
            failed = next(event for event in events if isinstance(event, AnswerAttemptFailed))
            starts = [event for event in events if isinstance(event, AnswerAttemptStarted)]
            assert [event.answer_kind for event in starts] == ["primary", "degraded"]
            assert events.index(failed) < events.index(starts[1])
        finally:
            release_terminal.set()
            await asyncio.wait_for(task, timeout=1)

        degraded_start = [
            event for event in events if isinstance(event, AnswerAttemptStarted)
        ][1]
        delta = next(event for event in events if isinstance(event, TextDelta))
        completed = next(event for event in events if isinstance(event, AgentCompleted))
        assert terminal_produced.is_set()
        assert delta.attempt_id == completed.attempt_id == degraded_start.attempt_id

    asyncio.run(exercise())


def test_partial_primary_text_is_published_then_replaced_after_provider_error() -> None:
    class _FailAfterTextModel:
        def stream(self, request: ModelRequest):
            async def generate():
                if request.step == 1:
                    yield ModelResponse.from_final("execution")
                elif request.step == 2:
                    yield ModelTextDelta(text="partial primary")
                    raise RuntimeError("primary failed after text")
                else:
                    yield ModelTextDelta(text="degraded answer")
                    yield ModelResponse.from_final("degraded answer")

            return generate()

    events = asyncio.run(
        _consume_stream(
            _runtime(_FailAfterTextModel()).run_stream([UserMessage(content="hello")]),
            [],
        )
    )

    starts = [event for event in events if isinstance(event, AnswerAttemptStarted)]
    failures = [event for event in events if isinstance(event, AnswerAttemptFailed)]
    deltas = [event for event in events if isinstance(event, TextDelta)]
    completed = next(event for event in events if isinstance(event, AgentCompleted))
    assert [event.text for event in deltas] == ["partial primary", "degraded answer"]
    assert len(failures) == 1 and failures[0].attempt_id == starts[0].attempt_id
    assert starts[0].attempt_id != starts[1].attempt_id
    assert events.index(deltas[0]) < events.index(failures[0]) < events.index(starts[1])
    assert deltas[1].attempt_id == completed.attempt_id == starts[1].attempt_id


def test_partial_primary_text_then_tool_response_fails_attempt_and_degrades() -> None:
    class _InvalidAnswerModel:
        def stream(self, request: ModelRequest):
            async def generate():
                if request.step == 1:
                    yield ModelResponse.from_final("execution")
                elif request.step == 2:
                    yield ModelTextDelta(text="visible before invalid response")
                    yield ModelResponse.from_assistant(
                        AssistantMessage(
                            tool_calls=[ToolCall(id="not-allowed", name="tool", arguments={})]
                        )
                    )
                else:
                    yield ModelResponse.from_final("degraded")

            return generate()

    events = asyncio.run(
        _consume_stream(
            _runtime(_InvalidAnswerModel()).run_stream([UserMessage(content="hello")]),
            [],
        )
    )

    starts = [event for event in events if isinstance(event, AnswerAttemptStarted)]
    failures = [event for event in events if isinstance(event, AnswerAttemptFailed)]
    completed = next(event for event in events if isinstance(event, AgentCompleted))
    assert [event.text for event in events if isinstance(event, TextDelta)] == [
        "visible before invalid response"
    ]
    assert len(failures) == 1 and failures[0].attempt_id == starts[0].attempt_id
    assert completed.attempt_id == starts[1].attempt_id
    assert not any(
        isinstance(event, AgentCompleted) and event.attempt_id == starts[0].attempt_id
        for event in events
    )


def test_partial_degraded_text_then_failure_is_replaced_by_deterministic_answer() -> None:
    class _FailBothAnswerAttemptsModel:
        def stream(self, request: ModelRequest):
            async def generate():
                if request.step == 1:
                    yield ModelResponse.from_final("execution")
                elif request.step == 2:
                    yield ModelTextDelta(text="partial primary")
                    raise RuntimeError("primary failed")
                else:
                    yield ModelTextDelta(text="partial degraded")
                    raise RuntimeError("degraded failed")

            return generate()

    events = asyncio.run(
        _consume_stream(
            _runtime(_FailBothAnswerAttemptsModel()).run_stream(
                [UserMessage(content="hello")]
            ),
            [],
        )
    )

    starts = [event for event in events if isinstance(event, AnswerAttemptStarted)]
    failures = [event for event in events if isinstance(event, AnswerAttemptFailed)]
    deltas = [event for event in events if isinstance(event, TextDelta)]
    completed = next(event for event in events if isinstance(event, AgentCompleted))
    assert [event.answer_kind for event in starts] == [
        "primary",
        "degraded",
        "deterministic",
    ]
    assert [event.text for event in deltas] == ["partial primary", "partial degraded"]
    assert [event.attempt_id for event in failures] == [
        starts[0].attempt_id,
        starts[1].attempt_id,
    ]
    assert len({event.attempt_id for event in starts}) == 3
    assert completed.attempt_id == starts[2].attempt_id
    assert completed.final.content not in [event.text for event in deltas]


@pytest.mark.parametrize(
    "violation",
    ["text_after_terminal", "duplicate_terminal", "missing_terminal"],
)
def test_stream_protocol_violations_after_partial_text_still_fail_attempt(
    violation: str,
) -> None:
    class _ProtocolViolationModel:
        def stream(self, request: ModelRequest):
            async def generate():
                if request.step == 1:
                    yield ModelResponse.from_final("execution")
                    return
                if request.step == 2:
                    yield ModelTextDelta(text="partial")
                    if violation == "missing_terminal":
                        return
                    yield ModelResponse.from_final("primary canonical")
                    if violation == "text_after_terminal":
                        yield ModelTextDelta(text="late")
                    else:
                        yield ModelResponse.from_final("duplicate")
                    return
                yield ModelResponse.from_final("degraded")

            return generate()

    events = asyncio.run(
        _consume_stream(
            _runtime(_ProtocolViolationModel()).run_stream([UserMessage(content="hello")]),
            [],
        )
    )

    starts = [event for event in events if isinstance(event, AnswerAttemptStarted)]
    failures = [event for event in events if isinstance(event, AnswerAttemptFailed)]
    assert [event.text for event in events if isinstance(event, TextDelta)] == ["partial"]
    assert len(failures) == 1 and failures[0].attempt_id == starts[0].attempt_id
    assert [event.answer_kind for event in starts] == ["primary", "degraded"]
    completed = next(event for event in events if isinstance(event, AgentCompleted))
    assert completed.attempt_id == starts[1].attempt_id


class _ClosableModel:
    def __init__(self) -> None:
        self.waiting_for_next = asyncio.Event()
        self.release_next = asyncio.Event()
        self.closed_streams = 0

    def stream(self, request: ModelRequest):
        async def generate():
            try:
                if request.step == 1:
                    yield ModelResponse.from_final("execution")
                    return
                yield ModelTextDelta(text="first")
                self.waiting_for_next.set()
                await self.release_next.wait()
                yield ModelTextDelta(text="second")
                yield ModelResponse.from_final("firstsecond")
            finally:
                self.closed_streams += 1

        return generate()


def test_cancellation_token_after_first_delta_closes_stream_without_fallback() -> None:
    async def exercise() -> None:
        model = _ClosableModel()
        token = CancellationToken()
        trace = AgentTraceCollector(capture_full_calls=True)
        stream = _runtime(model).run_stream(
            [UserMessage(content="hello")],
            cancellation_token=token,
            trace_collector=trace,
        )
        events: list[object] = []
        first_delta = asyncio.Event()

        async def consume() -> None:
            async for event in stream:
                events.append(event)
                if isinstance(event, TextDelta):
                    first_delta.set()

        task = asyncio.create_task(consume())
        await asyncio.wait_for(first_delta.wait(), timeout=1)
        await asyncio.wait_for(model.waiting_for_next.wait(), timeout=1)
        token.cancel()
        with pytest.raises(AgentCancelledError):
            await asyncio.wait_for(task, timeout=1)

        assert [event.text for event in events if isinstance(event, TextDelta)] == ["first"]
        assert not any(isinstance(event, AgentCompleted) for event in events)
        starts = [event for event in events if isinstance(event, AnswerAttemptStarted)]
        assert [event.answer_kind for event in starts] == ["primary"]
        assert isinstance(events[-1], AgentCancelled)
        assert model.closed_streams == 2  # execution and the cancelled answer stream
        assert trace.snapshot()["model_calls"][-1]["status"] == "cancelled"
        assert not [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]

    asyncio.run(exercise())


def test_consumer_task_cancellation_while_waiting_closes_provider_stream() -> None:
    async def exercise() -> None:
        model = _ClosableModel()
        trace = AgentTraceCollector(capture_full_calls=True)
        stream = _runtime(model).run_stream(
            [UserMessage(content="hello")],
            trace_collector=trace,
        )
        events: list[object] = []
        first_delta = asyncio.Event()

        async def consume() -> None:
            async for event in stream:
                events.append(event)
                if isinstance(event, TextDelta):
                    first_delta.set()

        task = asyncio.create_task(consume())
        await asyncio.wait_for(first_delta.wait(), timeout=1)
        await asyncio.wait_for(model.waiting_for_next.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        await stream.aclose()

        assert [event.text for event in events if isinstance(event, TextDelta)] == ["first"]
        assert not any(isinstance(event, (AgentCompleted, AnswerAttemptFailed)) for event in events)
        assert model.closed_streams == 2
        assert trace.snapshot()["model_calls"][-1]["status"] == "cancelled"
        assert not [
            pending
            for pending in asyncio.all_tasks()
            if pending is not asyncio.current_task() and not pending.done()
        ]

    asyncio.run(exercise())


def test_explicit_run_stream_close_after_delta_closes_nested_stream() -> None:
    async def exercise() -> None:
        model = _ClosableModel()
        trace = AgentTraceCollector(capture_full_calls=True)
        stream = _runtime(model).run_stream(
            [UserMessage(content="hello")],
            trace_collector=trace,
        )
        events: list[object] = []
        while True:
            event = await asyncio.wait_for(anext(stream), timeout=1)
            events.append(event)
            if isinstance(event, TextDelta):
                break
        await stream.aclose()

        assert [event.text for event in events if isinstance(event, TextDelta)] == ["first"]
        assert not any(isinstance(event, (AgentCompleted, AnswerAttemptFailed)) for event in events)
        assert model.closed_streams == 2
        assert trace.snapshot()["model_calls"][-1]["status"] == "cancelled"
        starts = [event for event in events if isinstance(event, AnswerAttemptStarted)]
        assert [event.answer_kind for event in starts] == ["primary"]

    asyncio.run(exercise())


def test_execution_and_compaction_text_are_traced_but_not_answer_events() -> None:
    request_id = uuid4()
    history = SessionExecutionHistory()
    history.begin_request(
        request_id,
        "current question",
        initial_messages=[
            UserMessage(content="older question"),
            FinalMessage(content="older answer"),
            UserMessage(content="current question"),
        ],
    )
    history.set_effective(
        [
            UserMessage(content="older question"),
            FinalMessage(content="older answer"),
            UserMessage(content="current question"),
            AssistantMessage(content="early progress"),
            AssistantMessage(content="recent progress"),
            FinalMessage(content="recent final"),
        ]
    )

    class _PrivateTextModel:
        def stream(self, request: ModelRequest):
            async def generate():
                if request.metadata.get("purpose") == "context_compaction":
                    yield ModelTextDelta(text="private compaction text")
                    yield ModelResponse.from_final(
                        "compressed history",
                        finish_reason="stop",
                    )
                elif request.step == 1:
                    yield ModelTextDelta(text="private execution text")
                    yield ModelResponse.from_final("execution")
                else:
                    yield ModelTextDelta(text="visible answer text")
                    yield ModelResponse.from_final("canonical answer")

            return generate()

    trace = AgentTraceCollector(capture_full_calls=True)
    runtime = AgentRuntime(
        _PrivateTextModel(),  # type: ignore[arg-type]
        ToolRegistry(),
        limits=AgentLimits(
            deadline_seconds=3,
            answer_timeout_seconds=3,
            compaction_keep_recent_tokens=1,
        ),
    )

    async def collect() -> list[object]:
        events: list[object] = []
        async for event in runtime.run_stream(
            history.effective_messages(),
            execution_history=history,
            request_id=request_id,
            compact_before_steps=(1,),
            trace_collector=trace,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect())

    assert [event.text for event in events if isinstance(event, TextDelta)] == [
        "visible answer text"
    ]
    partial_text = "".join(
        call.get("partial_text", "")
        for call in trace.snapshot()["model_calls"]
    )
    assert [call["purpose"] for call in trace.snapshot()["model_calls"]] == [
        "compaction",
        "compaction",
        "execution",
        "primary_answer",
    ]
    assert "private compaction text" in partial_text
    assert "private execution text" in partial_text
    assert "visible answer text" in partial_text
    assert next(event for event in events if isinstance(event, AgentCompleted)).final.content == (
        "canonical answer"
    )


def test_sink_and_iterator_receive_each_fragment_once_without_final_duplication() -> None:
    class _TwoPartModel:
        def stream(self, request: ModelRequest):
            async def generate():
                if request.step == 1:
                    yield ModelResponse.from_final("execution")
                else:
                    yield ModelTextDelta(text="part one")
                    yield ModelTextDelta(text="part two")
                    yield ModelResponse.from_final("canonical full text")

            return generate()

    runtime = _runtime(_TwoPartModel())
    sink_events: list[object] = []

    async def sink(event: object) -> None:
        sink_events.append(event)

    events = asyncio.run(
        _consume_stream(
            runtime.run_stream([UserMessage(content="hello")], event_sink=sink),
            [],
        )
    )

    assert sink_events == events
    deltas = [event for event in events if isinstance(event, TextDelta)]
    completed = next(event for event in events if isinstance(event, AgentCompleted))
    assert [event.text for event in deltas] == ["part one", "part two"]
    assert completed.final.content == "canonical full text"
    assert completed.final.content not in [event.text for event in deltas]
    assert len(deltas) == 2


def test_complete_only_model_returns_final_without_synthetic_deltas() -> None:
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )
    events = asyncio.run(
        _consume_stream(
            _runtime(model).run_stream([UserMessage(content="hello")]),
            [],
        )
    )

    assert not any(isinstance(event, TextDelta) for event in events)
    started = next(event for event in events if isinstance(event, AnswerAttemptStarted))
    completed = next(event for event in events if isinstance(event, AgentCompleted))
    assert completed.final.content == "answer"
    assert completed.attempt_id == started.attempt_id
    assert len(model.requests) == 2


async def _consume_stream(stream, events: list[object], on_delta=None) -> list[object]:
    async for event in stream:
        events.append(event)
        if on_delta is not None and isinstance(event, TextDelta):
            on_delta.set()
    return events
