from __future__ import annotations

import asyncio
from collections.abc import Callable
from uuid import uuid4

import pytest
from pydantic import BaseModel

import app.vnext.agent.runtime as runtime_module
from app.vnext.agent.answer_stage import AnswerProjectionMode
from app.vnext.agent.errors import (
    AgentCancelledError,
    ContextCapacityExceeded,
    ModelContextWindowExceeded,
)
from app.vnext.agent.events import (
    AgentCancelled,
    AgentCompleted,
    AnswerAttemptFailed,
    AnswerAttemptStarted,
    AnswerStageStarted,
    ExecutionCommentary,
    TextDelta,
    ToolStarted,
)
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime, CancellationToken
from app.vnext.agent.task_state import TaskPlan, TaskStateCoordinator
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.errors import ModelContextWindowError
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelRequest,
    ModelResponse,
    ModelTextDelta,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools import ToolDefinition, ToolRegistry
from tests.vnext.fakes import ScriptedModelClient, ScriptedStreamingModelClient


async def _collect(runtime: AgentRuntime, **kwargs: object) -> list[object]:
    events: list[object] = []
    async for event in runtime.run_stream([UserMessage(content="hello")], **kwargs):
        events.append(event)
    return events


def _collect_sync(runtime: AgentRuntime, **kwargs: object) -> list[object]:
    return asyncio.run(_collect(runtime, **kwargs))


def _overflow() -> ModelContextWindowExceeded:
    cause = ModelContextWindowError(
        provider_code="context_length_exceeded",
        status_code=400,
    )
    return ModelContextWindowExceeded(
        cause=cause,
        provider_code="context_length_exceeded",
        status_code=400,
    )


def _history(*, compactable: bool) -> tuple[SessionExecutionHistory, object]:
    history = SessionExecutionHistory()
    request_id = uuid4()
    messages = [UserMessage(content="current question")]
    if compactable:
        call = ToolCall(id="old-call", name="old.tool", arguments={})
        messages = [
            UserMessage(content="older question"),
            AssistantMessage(tool_calls=[call]),
            ToolResultMessage(tool_call_id=call.id, content={"fact": "older evidence"}),
            UserMessage(content="current question"),
        ]
    history.begin_request(
        request_id,
        "current question",
        initial_messages=messages,
    )
    return history, request_id


def _overflow_limits() -> AgentLimits:
    return AgentLimits(
        deadline_seconds=5,
        answer_timeout_seconds=5,
        compaction_keep_recent_tokens=1,
        compaction_reserve_tokens=160,
        context_window_tokens=100_000,
        application_max_output_tokens=64,
        context_safety_margin_tokens=16,
        context_estimate_bytes_per_token=1,
    )


class _PlannedModel:
    def __init__(self, plans: list[Callable[[ModelRequest], ModelResponse] | Exception]) -> None:
        self.plans = list(plans)
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self.plans:
            raise AssertionError("model plan was exhausted")
        plan = self.plans.pop(0)
        if isinstance(plan, Exception):
            raise plan
        return plan(request)


def _final(content: str) -> Callable[[ModelRequest], ModelResponse]:
    return lambda _request: ModelResponse.from_final(content)


def _summary(request: ModelRequest) -> ModelResponse:
    assert request.metadata.get("purpose") == "context_compaction"
    return ModelResponse.from_final("compressed background", finish_reason="stop")


def test_normal_success_has_one_stage_and_primary_identity_for_text_and_final() -> None:
    model = ScriptedStreamingModelClient(
        [
            [ModelResponse.from_final("execution")],
            [ModelTextDelta(text="answer "), ModelResponse.from_final("answer")],
        ]
    )
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=2, application_max_output_tokens=4096),
    )

    events = _collect_sync(runtime)

    stages = [event for event in events if isinstance(event, AnswerStageStarted)]
    starts = [event for event in events if isinstance(event, AnswerAttemptStarted)]
    deltas = [event for event in events if isinstance(event, TextDelta)]
    completed = [event for event in events if isinstance(event, AgentCompleted)]
    assert len(stages) == 1
    assert [event.answer_kind for event in starts] == ["primary"]
    assert events.index(stages[0]) < events.index(starts[0]) < events.index(deltas[0])
    assert deltas[0].attempt_id == starts[0].attempt_id == completed[0].attempt_id
    assert events.index(deltas[0]) < events.index(completed[0])
    assert not any(isinstance(event, ExecutionCommentary) for event in events)


def test_accepted_multi_tool_response_publishes_one_commentary_before_tools() -> None:
    class _ToolInput(BaseModel):
        value: int

    class _ToolOutput(BaseModel):
        value: int

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="Echo an integer.",
            input_model=_ToolInput,
            output_model=_ToolOutput,
            handler=lambda args: _ToolOutput(value=args.value),
            parallel_safe=True,
        )
    )
    response = ModelResponse(
        message=AssistantMessage(
            content="  正在查询赛事。\n准备读取详情。  ",
            tool_calls=[
                ToolCall(id="call-1", name="echo", arguments={"value": 1}),
                ToolCall(id="call-2", name="echo", arguments={"value": 2}),
            ],
        )
    )
    model = _PlannedModel([lambda _request: response, _final("最终回答")])
    runtime = AgentRuntime(
        model,
        registry,
        limits=AgentLimits(deadline_seconds=2, application_max_output_tokens=4096),
    )

    events = _collect_sync(runtime)

    commentary = [event for event in events if isinstance(event, ExecutionCommentary)]
    tool_starts = [event for event in events if isinstance(event, ToolStarted)]
    assert len(commentary) == 1
    assert commentary[0].step == 1
    assert commentary[0].text == "  正在查询赛事。\n准备读取详情。  "
    assert len(tool_starts) == 2
    assert events.index(commentary[0]) < min(events.index(event) for event in tool_starts)
    completed = next(event for event in events if isinstance(event, AgentCompleted))
    assert "正在查询赛事" not in completed.final.content
    assert all(
        not isinstance(event, TextDelta) or "正在查询赛事" not in event.text
        for event in events
    )


def test_blank_commentary_on_an_accepted_tool_call_is_not_published() -> None:
    class _ToolInput(BaseModel):
        value: int

    class _ToolOutput(BaseModel):
        value: int

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="Echo an integer.",
            input_model=_ToolInput,
            output_model=_ToolOutput,
            handler=lambda args: _ToolOutput(value=args.value),
        )
    )
    response = ModelResponse(
        message=AssistantMessage(
            content=" \n\t ",
            tool_calls=[ToolCall(id="call-1", name="echo", arguments={"value": 1})],
        )
    )
    model = _PlannedModel([lambda _request: response, _final("done")])
    runtime = AgentRuntime(
        model,
        registry,
        limits=AgentLimits(deadline_seconds=2, application_max_output_tokens=4096),
    )

    events = _collect_sync(runtime)

    assert not any(isinstance(event, ExecutionCommentary) for event in events)


def test_direct_deterministic_answer_does_not_add_a_model_call() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.plan = TaskPlan(items=(), current_key=None)
    model = ScriptedModelClient([ModelResponse.from_final("execution")])
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=2, application_max_output_tokens=4096),
        task_state_coordinator=coordinator,
    )

    events = _collect_sync(runtime)

    lifecycle = [
        event
        for event in events
        if isinstance(event, (AnswerStageStarted, AnswerAttemptStarted, AgentCompleted))
    ]
    assert [type(event) for event in lifecycle] == [
        AnswerStageStarted,
        AnswerAttemptStarted,
        AgentCompleted,
    ]
    assert lifecycle[1].answer_kind == "deterministic"  # type: ignore[union-attr]
    assert lifecycle[1].attempt_id == lifecycle[2].attempt_id  # type: ignore[union-attr]
    assert len(model.requests) == 1


def test_primary_failure_then_degraded_success_uses_new_identity() -> None:
    model = ScriptedStreamingModelClient(
        [
            [ModelResponse.from_final("execution")],
            [RuntimeError("primary unavailable")],
            [ModelTextDelta(text="degraded "), ModelResponse.from_final("degraded")],
        ]
    )
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=2, application_max_output_tokens=4096),
    )

    events = _collect_sync(runtime)

    starts = [event for event in events if isinstance(event, AnswerAttemptStarted)]
    failures = [event for event in events if isinstance(event, AnswerAttemptFailed)]
    delta = next(event for event in events if isinstance(event, TextDelta))
    completed = next(event for event in events if isinstance(event, AgentCompleted))
    assert [event.answer_kind for event in starts] == ["primary", "degraded"]
    assert starts[0].attempt_id != starts[1].attempt_id
    assert len(failures) == 1 and failures[0].attempt_id == starts[0].attempt_id
    assert events.index(failures[0]) < events.index(starts[1])
    assert delta.attempt_id == completed.attempt_id == starts[1].attempt_id


def test_primary_and_degraded_failure_select_deterministic_once() -> None:
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("execution"),
            RuntimeError("primary unavailable"),
            RuntimeError("degraded unavailable"),
        ]
    )
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=2, application_max_output_tokens=4096),
    )

    events = _collect_sync(runtime)

    lifecycle = [
        event
        for event in events
        if isinstance(
            event,
            (AnswerStageStarted, AnswerAttemptStarted, AnswerAttemptFailed, AgentCompleted),
        )
    ]
    assert [type(event) for event in lifecycle] == [
        AnswerStageStarted,
        AnswerAttemptStarted,
        AnswerAttemptFailed,
        AnswerAttemptStarted,
        AnswerAttemptFailed,
        AnswerAttemptStarted,
        AgentCompleted,
    ]
    starts = [event for event in lifecycle if isinstance(event, AnswerAttemptStarted)]
    failures = [event for event in lifecycle if isinstance(event, AnswerAttemptFailed)]
    completed = lifecycle[-1]
    assert [event.answer_kind for event in starts] == [
        "primary",
        "degraded",
        "deterministic",
    ]
    assert len({event.attempt_id for event in starts}) == 3
    assert [event.attempt_id for event in failures] == [
        starts[0].attempt_id,
        starts[1].attempt_id,
    ]
    assert completed.attempt_id == starts[2].attempt_id  # type: ignore[union-attr]


def test_primary_overflow_recovery_starts_a_new_attempt() -> None:
    history, request_id = _history(compactable=True)
    model = _PlannedModel(
        [_final("execution"), _overflow(), _summary, _final("answer")]
    )
    trace = AgentTraceCollector()
    runtime = AgentRuntime(model, ToolRegistry(), limits=_overflow_limits())

    async def collect() -> list[object]:
        events: list[object] = []
        async for event in runtime.run_stream(
            history.effective_messages(),
            execution_history=history,
            request_id=request_id,
            trace_collector=trace,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect())

    starts = [event for event in events if isinstance(event, AnswerAttemptStarted)]
    failures = [event for event in events if isinstance(event, AnswerAttemptFailed)]
    completed = next(event for event in events if isinstance(event, AgentCompleted))
    assert [event.answer_kind for event in starts] == ["primary", "primary"]
    assert starts[0].attempt_id != starts[1].attempt_id
    assert len(failures) == 1 and failures[0].attempt_id == starts[0].attempt_id
    assert events.index(failures[0]) < events.index(starts[1])
    assert completed.attempt_id == starts[1].attempt_id
    assert len(model.requests) == 4
    assert sum(not request.metadata for request in model.requests) == 3
    assert (
        sum(
            request.metadata.get("purpose") == "context_compaction"
            for request in model.requests
        )
        == 1
    )
    assert trace.snapshot()["overflow_recoveries"] == [
        {
            "step": 2,
            "stage": "primary_answer",
            "status": "retry_succeeded",
            "error_code": None,
        }
    ]


def test_failed_overflow_recovery_does_not_duplicate_failure_or_invent_retry() -> None:
    history, request_id = _history(compactable=False)
    model = _PlannedModel([_final("execution"), _overflow(), _final("degraded")])
    runtime = AgentRuntime(model, ToolRegistry(), limits=_overflow_limits())

    async def collect() -> list[object]:
        events: list[object] = []
        async for event in runtime.run_stream(
            history.effective_messages(),
            execution_history=history,
            request_id=request_id,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect())

    starts = [event for event in events if isinstance(event, AnswerAttemptStarted)]
    failures = [event for event in events if isinstance(event, AnswerAttemptFailed)]
    completed = next(event for event in events if isinstance(event, AgentCompleted))
    assert [event.answer_kind for event in starts] == ["primary", "degraded"]
    assert len(failures) == 1 and failures[0].attempt_id == starts[0].attempt_id
    assert completed.attempt_id == starts[1].attempt_id
    assert len(model.requests) == 3
    assert not any(
        request.metadata.get("purpose") == "context_compaction"
        for request in model.requests
    )


def test_primary_preparation_capacity_failure_has_attempt_without_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_builder = runtime_module.AnswerContextBuilder

    class _FailPrimaryPreparation:
        def build(self, **kwargs: object):  # type: ignore[no-untyped-def]
            if kwargs.get("projection_mode") is AnswerProjectionMode.PRIMARY:
                raise ContextCapacityExceeded("primary context is too large")
            return original_builder().build(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runtime_module, "AnswerContextBuilder", _FailPrimaryPreparation)
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("degraded")]
    )
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=2, application_max_output_tokens=4096),
    )

    events = _collect_sync(runtime)

    starts = [event for event in events if isinstance(event, AnswerAttemptStarted)]
    failures = [event for event in events if isinstance(event, AnswerAttemptFailed)]
    assert [event.answer_kind for event in starts] == ["primary", "degraded"]
    assert len(failures) == 1
    assert failures[0].attempt_id == starts[0].attempt_id
    assert failures[0].error_code == ContextCapacityExceeded.code
    assert len(model.requests) == 2  # execution and degraded; primary preparation made no call
    assert next(event for event in events if isinstance(event, AgentCompleted)).attempt_id == (
        starts[1].attempt_id
    )


def test_cancellation_during_answer_does_not_fail_attempt_or_start_fallback() -> None:
    token = CancellationToken()
    stream_started = asyncio.Event()

    class _BlockingModel:
        async def complete(self, _request: ModelRequest) -> ModelResponse:
            return ModelResponse.from_final("execution")

        def stream(self, request: ModelRequest):
            async def emit():
                if request.step == 1:
                    yield ModelResponse.from_final("execution")
                    return
                yield ModelTextDelta(text="unpublished partial")
                stream_started.set()
                await asyncio.Future()

            return emit()

    runtime = AgentRuntime(
        _BlockingModel(),  # type: ignore[arg-type]
        ToolRegistry(),
        limits=AgentLimits(
            deadline_seconds=2,
            answer_timeout_seconds=2,
            application_max_output_tokens=4096,
        ),
    )
    events: list[object] = []

    async def run_and_cancel() -> None:
        async def consume() -> None:
            async for event in runtime.run_stream(
                [UserMessage(content="hello")],
                cancellation_token=token,
            ):
                events.append(event)

        task = asyncio.create_task(consume())
        await stream_started.wait()
        token.cancel()
        with pytest.raises(AgentCancelledError):
            await task

    asyncio.run(run_and_cancel())

    assert not any(isinstance(event, (AnswerAttemptFailed, AgentCompleted)) for event in events)
    assert [event.text for event in events if isinstance(event, TextDelta)] == [
        "unpublished partial"
    ]
    assert [event.answer_kind for event in events if isinstance(event, AnswerAttemptStarted)] == [
        "primary"
    ]
    assert isinstance(events[-1], AgentCancelled)


def test_attempt_identity_is_local_to_each_runtime_invocation() -> None:
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("execution 1"),
            ModelResponse.from_final("answer 1"),
            ModelResponse.from_final("execution 2"),
            ModelResponse.from_final("answer 2"),
        ]
    )
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=2, application_max_output_tokens=4096),
    )

    first = _collect_sync(runtime)
    second = _collect_sync(runtime)

    for events in (first, second):
        started = next(event for event in events if isinstance(event, AnswerAttemptStarted))
        completed = next(event for event in events if isinstance(event, AgentCompleted))
        assert started.attempt_id == completed.attempt_id == "answer-1"


def test_event_sink_receives_same_single_ordered_stream_as_iterator() -> None:
    model = ScriptedStreamingModelClient(
        [
            [ModelResponse.from_final("execution")],
            [ModelTextDelta(text="answer"), ModelResponse.from_final("answer")],
        ]
    )
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=2, application_max_output_tokens=4096),
    )
    sink_events: list[object] = []

    async def sink(event: object) -> None:
        sink_events.append(event)

    iterator_events = _collect_sync(runtime, event_sink=sink)

    assert sink_events == iterator_events
    assert sum(isinstance(event, AnswerStageStarted) for event in iterator_events) == 1
    assert sum(isinstance(event, AnswerAttemptStarted) for event in iterator_events) == 1
    assert sum(isinstance(event, TextDelta) for event in iterator_events) == 1
    assert sum(isinstance(event, AgentCompleted) for event in iterator_events) == 1


def test_hand_constructed_answer_events_keep_none_identity_default() -> None:
    assert TextDelta(text="legacy").attempt_id is None
    assert AgentCompleted(
        duration=0.1,
        final=FinalMessage(content="legacy"),
    ).attempt_id is None
