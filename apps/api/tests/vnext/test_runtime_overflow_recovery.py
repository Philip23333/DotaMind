from __future__ import annotations

import asyncio
from collections.abc import Callable
from time import monotonic
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.vnext.agent.context_capacity import assess_request_capacity
from app.vnext.agent.errors import (
    AgentCancelledError,
    AgentRuntimeError,
    ModelContextWindowExceeded,
    ModelProviderError,
)
from app.vnext.agent.events import ModelRequested, TextDelta, ToolStarted
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime, CancellationToken, _Deadline
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.errors import ModelContextWindowError
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelRequest,
    ModelResponse,
    ModelTextDelta,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry


class _EchoInput(BaseModel):
    text: str


class _EchoOutput(BaseModel):
    text: str


def _call(call_id: str = "call-1", text: str = "value") -> ToolCall:
    return ToolCall(id=call_id, name="echo", arguments={"text": text})


def _registry(calls: list[str] | None = None) -> ToolRegistry:
    registry = ToolRegistry()

    async def echo(arguments: _EchoInput) -> _EchoOutput:
        if calls is not None:
            calls.append(arguments.text)
        return _EchoOutput(text=arguments.text)

    registry.register(
        ToolDefinition(
            name="echo",
            description="Return the input.",
            input_model=_EchoInput,
            output_model=_EchoOutput,
            handler=echo,
        )
    )
    return registry


def _history(messages: list[object] | None = None) -> tuple[SessionExecutionHistory, object]:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(
        request_id,
        "current question",
        initial_messages=(
            messages
            or [
                UserMessage(content="old question"),
                AssistantMessage(tool_calls=[_call("old-call", "old")]),
                ToolResultMessage(
                    tool_call_id="old-call",
                    content={"text": "old evidence"},
                ),
                UserMessage(content="current question"),
            ]
        ),  # type: ignore[arg-type]
    )
    return history, request_id


def _limits(
    *,
    max_steps: int = 3,
    context_window_tokens: int | None = 100_000,
) -> AgentLimits:
    return AgentLimits(
        max_steps=max_steps,
        deadline_seconds=5,
        answer_timeout_seconds=5,
        degraded_answer_timeout_seconds=5,
        compaction_recent_history_bytes=1,
        compaction_max_input_bytes=100_000,
        compaction_max_output_tokens=128,
        compaction_max_summary_bytes=10_000,
        context_window_tokens=context_window_tokens,
        context_output_reserve_tokens=64,
        context_safety_margin_tokens=16,
        context_estimate_bytes_per_token=1,
    )


class _PlannedModel:
    def __init__(self, plans: list[Callable[[ModelRequest], ModelResponse]]) -> None:
        self.plans = plans
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self.plans:
            raise AssertionError("model plan was exhausted")
        return self.plans.pop(0)(request)


def _final(content: str) -> Callable[[ModelRequest], ModelResponse]:
    return lambda request: ModelResponse.from_final(content, finish_reason="stop")


def _overflow(status_code: int = 400) -> Callable[[ModelRequest], ModelResponse]:
    def fail(request: ModelRequest) -> ModelResponse:
        raise ModelContextWindowExceeded(
            cause=ModelContextWindowError(
                provider_code="context_length_exceeded",
                status_code=status_code,
            ),
            provider_code="context_length_exceeded",
            status_code=status_code,
        )

    return fail


def _summary(content: str = "compressed background") -> Callable[[ModelRequest], ModelResponse]:
    def generate(request: ModelRequest) -> ModelResponse:
        assert request.metadata.get("purpose") == "context_compaction"
        assert request.tools == []
        return ModelResponse.from_final(content, finish_reason="stop")

    return generate


def _run(runtime: AgentRuntime, history: SessionExecutionHistory, request_id: object, **kwargs):
    async def run() -> object:
        return await asyncio.wait_for(
            runtime.run(
                history.effective_messages(),
                execution_history=history,
                request_id=request_id,
                **kwargs,
            ),
            timeout=3,
        )

    return asyncio.run(run())


def _execution_request(
    history: SessionExecutionHistory,
    limits: AgentLimits,
) -> ModelRequest:
    request, *_ = AgentRuntime(
        _PlannedModel([]),
        _registry(),
        limits=limits,
    )._build_execution_request(
        request_messages=history.effective_messages(),
        execution_history=history,
        step=1,
        deadline=_Deadline(None),
        auto_compaction_enabled=True,
    )
    return request


def test_execution_overflow_compacts_and_retries_same_step() -> None:
    history, request_id = _history()
    model = _PlannedModel(
        [_overflow(), _summary(), _final("execution"), _final("answer")]
    )
    trace = AgentTraceCollector()
    events: list[object] = []

    async def sink(event: object) -> None:
        events.append(event)

    result = _run(
        AgentRuntime(model, _registry(), limits=_limits()),
        history,
        request_id,
        trace_collector=trace,
        event_sink=sink,
    )

    assert result.content == "answer"  # type: ignore[union-attr]
    business_requests = [request for request in model.requests if not request.metadata]
    assert [request.step for request in business_requests] == [1, 1, 2]
    assert "compressed background" in str(business_requests[1].messages)
    assert [event.step for event in events if isinstance(event, ModelRequested)] == [1, 1, 2]
    snapshot = trace.snapshot()
    assert snapshot["overflow_recoveries"] == [
        {
            "step": 1,
            "stage": "execution",
            "status": "retry_succeeded",
            "error_code": None,
        }
    ]
    assert snapshot["compaction_commits"][0]["trigger"] == "overflow"
    assert snapshot["steps"][0]["failed_model_attempts"][0]["error_code"] == (
        "model_context_window_exceeded"
    )


def test_overflow_recovery_does_not_replay_completed_tools() -> None:
    history, request_id = _history()
    calls: list[str] = []
    model = _PlannedModel(
        [
            lambda request: ModelResponse.from_assistant(
                AssistantMessage(tool_calls=[_call("new-call", "new")])
            ),
            _overflow(),
            _summary(),
            _final("execution"),
            _final("answer"),
        ]
    )
    events: list[object] = []

    async def sink(event: object) -> None:
        events.append(event)

    result = _run(
        AgentRuntime(model, _registry(calls), limits=_limits(max_steps=3)),
        history,
        request_id,
        event_sink=sink,
    )

    assert result.content == "answer"  # type: ignore[union-attr]
    assert calls == ["new"]
    assert [event.tool_call_id for event in events if isinstance(event, ToolStarted)] == [
        "new-call"
    ]
    assert len([request for request in model.requests if request.tools]) == 3


def test_watermark_compaction_still_allows_one_overflow_recovery() -> None:
    old_call = _call("old-call", "old")
    messages = [
        UserMessage(content="old question"),
        AssistantMessage(tool_calls=[old_call]),
        ToolResultMessage(
            tool_call_id=old_call.id,
            content={"text": "old evidence " + ("o" * 4_200)},
        ),
        UserMessage(content="current question"),
    ]
    history, request_id = _history(messages)
    compacted_history, compacted_request_id = _history(messages)
    watermark_summary = "watermark summary"
    compacted_history.commit_compaction(
        request_id=compacted_request_id,  # type: ignore[arg-type]
        base_revision=compacted_history.revision,
        summary=watermark_summary,
        cut_index=3,
    )
    limits = _limits(context_window_tokens=6_000)
    initial_capacity = assess_request_capacity(_execution_request(history, limits), limits)
    assert initial_capacity is not None
    assert initial_capacity.pressure.value == "high"

    model = _PlannedModel(
        [
            _summary(watermark_summary),
            lambda request: ModelResponse.from_assistant(
                AssistantMessage(tool_calls=[_call("new-call", "new")])
            ),
            lambda request: ModelResponse.from_assistant(
                AssistantMessage(tool_calls=[_call("new-call-2", "new-2")])
            ),
            _overflow(),
            _summary(),
            _final("execution"),
            _final("answer"),
        ]
    )
    trace = AgentTraceCollector()

    result = _run(
        AgentRuntime(model, _registry(), limits=limits),
        history,
        request_id,
        trace_collector=trace,
    )

    assert result.content == "answer"  # type: ignore[union-attr]
    assert [commit["trigger"] for commit in trace.snapshot()["compaction_commits"]] == [
        "watermark",
        "overflow",
    ]
    assert trace.snapshot()["overflow_recoveries"][0]["status"] == "retry_succeeded"


def test_overflow_compaction_that_remains_critical_does_not_retry() -> None:
    old_call = _call("old-call", "old")
    messages = [
        UserMessage(content="old question"),
        AssistantMessage(tool_calls=[old_call]),
        ToolResultMessage(
            tool_call_id=old_call.id,
            content={"text": "old evidence " + ("o" * 4_200)},
        ),
        UserMessage(content="current question"),
    ]
    history, request_id = _history(messages)
    compacted_history, compacted_request_id = _history(messages)
    oversized_summary = "compressed background " + ("s" * 6_500)
    compacted_history.commit_compaction(
        request_id=compacted_request_id,  # type: ignore[arg-type]
        base_revision=compacted_history.revision,
        summary=oversized_summary,
        cut_index=3,
    )
    probe_limits = _limits()
    initial_request = _execution_request(history, probe_limits)
    compacted_request = _execution_request(compacted_history, probe_limits)
    initial_capacity = assess_request_capacity(initial_request, probe_limits)
    compacted_capacity = assess_request_capacity(compacted_request, probe_limits)
    assert initial_capacity is not None
    assert compacted_capacity is not None
    limits: AgentLimits | None = None
    for window in range(
        max(initial_capacity.estimated_input_tokens + 80, 100),
        compacted_capacity.estimated_input_tokens + 160,
    ):
        candidate_limits = _limits(context_window_tokens=window)
        candidate_initial = assess_request_capacity(
            _execution_request(history, candidate_limits),
            candidate_limits,
        )
        candidate_compacted = assess_request_capacity(
            _execution_request(compacted_history, candidate_limits),
            candidate_limits,
        )
        assert candidate_initial is not None
        assert candidate_compacted is not None
        if (
            candidate_initial.pressure.value == "normal"
            and candidate_compacted.pressure.value == "critical"
        ):
            limits = candidate_limits
            break
    assert limits is not None, (
        initial_capacity.estimated_input_tokens,
        compacted_capacity.estimated_input_tokens,
    )
    model = _PlannedModel([_overflow(), _summary(oversized_summary)])
    trace = AgentTraceCollector()

    result = _run(
        AgentRuntime(model, _registry(), limits=limits),
        history,
        request_id,
        trace_collector=trace,
    )

    assert "context budget was exhausted" in result.content  # type: ignore[union-attr]
    assert len(model.requests) == 2
    assert len(history.compaction_records) == 1
    assert trace.snapshot()["overflow_recoveries"][0]["status"] == "capacity_exceeded"
    assert trace.snapshot()["execution_outcome"]["reason"] == "context_capacity"


def test_primary_answer_overflow_rebuilds_tool_free_request() -> None:
    history, request_id = _history()
    model = _PlannedModel([_final("execution"), _overflow(), _summary(), _final("answer")])
    trace = AgentTraceCollector()

    result = _run(
        AgentRuntime(model, _registry(), limits=_limits()),
        history,
        request_id,
        trace_collector=trace,
    )

    assert result.content == "answer"  # type: ignore[union-attr]
    answer_requests = [
        request for request in model.requests if not request.tools and not request.metadata
    ]
    assert len(answer_requests) == 2
    assert answer_requests[0].max_output_tokens == answer_requests[1].max_output_tokens
    assert "compressed background" in str(answer_requests[1].messages)
    assert trace.snapshot()["overflow_recoveries"] == [
        {
            "step": 2,
            "stage": "primary_answer",
            "status": "retry_succeeded",
            "error_code": None,
        }
    ]


def test_rebuild_deadline_expires_before_retry_event_or_request() -> None:
    history, request_id = _history()
    model = _PlannedModel([_overflow(), _summary()])
    trace = AgentTraceCollector()
    events: list[object] = []

    async def sink(event: object) -> None:
        events.append(event)

    class DeadlineDuringRebuildRuntime(AgentRuntime):
        build_count = 0

        def _build_execution_request(self, **kwargs):  # type: ignore[no-untyped-def]
            self.build_count += 1
            result = super()._build_execution_request(**kwargs)
            if self.build_count == 2:
                deadline = kwargs["deadline"]
                deadline.expires_at = monotonic() - 1
            return result

    result = _run(
        DeadlineDuringRebuildRuntime(model, _registry(), limits=_limits()),
        history,
        request_id,
        trace_collector=trace,
        event_sink=sink,
    )

    assert "execution stopped before" in result.content  # type: ignore[union-attr]
    assert len(model.requests) == 2
    assert [event.step for event in events if isinstance(event, ModelRequested)] == [1]
    assert trace.snapshot()["overflow_recoveries"][0]["status"] == "deadline_exceeded"


def test_invalid_primary_retry_response_is_not_recorded_as_recovery_success() -> None:
    history, request_id = _history()
    model = _PlannedModel(
        [
            _final("execution"),
            _overflow(),
            _summary(),
            lambda request: ModelResponse.from_assistant(
                AssistantMessage(tool_calls=[_call("invalid-answer")])
            ),
            _final("degraded"),
        ]
    )
    trace = AgentTraceCollector()

    result = _run(
        AgentRuntime(model, _registry(), limits=_limits()),
        history,
        request_id,
        trace_collector=trace,
    )

    assert result.content == "degraded"  # type: ignore[union-attr]
    assert trace.snapshot()["overflow_recoveries"] == [
        {
            "step": 2,
            "stage": "primary_answer",
            "status": "retry_failed",
            "error_code": "model_protocol_error",
        }
    ]


def test_execution_recovery_uses_shared_quota_for_primary_answer() -> None:
    history, request_id = _history()
    model = _PlannedModel(
        [_overflow(), _summary(), _final("execution"), _overflow(), _final("degraded")]
    )
    trace = AgentTraceCollector()

    result = _run(
        AgentRuntime(model, _registry(), limits=_limits()),
        history,
        request_id,
        trace_collector=trace,
    )

    assert result.content == "degraded"  # type: ignore[union-attr]
    assert (
        len(
            [
                request
                for request in model.requests
                if request.metadata.get("purpose") == "context_compaction"
            ]
        )
        == 1
    )
    assert len(trace.snapshot()["overflow_recoveries"]) == 1


def test_overflow_without_compactable_range_does_not_retry_or_summarize() -> None:
    history, request_id = _history([UserMessage(content="current question")])
    model = _PlannedModel([_overflow()])
    trace = AgentTraceCollector()

    with pytest.raises(ModelContextWindowExceeded):
        _run(
            AgentRuntime(model, _registry(), limits=_limits()),
            history,
            request_id,
            trace_collector=trace,
        )

    assert len(model.requests) == 1
    assert trace.snapshot()["overflow_recoveries"][0]["status"] == "no_compactable_range"
    assert "compaction_calls" not in trace.snapshot()


def test_retry_overflow_does_not_start_a_second_recovery() -> None:
    history, request_id = _history()
    model = _PlannedModel([_overflow(), _summary(), _overflow()])
    trace = AgentTraceCollector()

    with pytest.raises(ModelContextWindowExceeded):
        _run(
            AgentRuntime(model, _registry(), limits=_limits()),
            history,
            request_id,
            trace_collector=trace,
        )

    assert len(model.requests) == 3
    assert (
        len(
            [
                request
                for request in model.requests
                if request.metadata.get("purpose") == "context_compaction"
            ]
        )
        == 1
    )
    assert trace.snapshot()["overflow_recoveries"][0]["status"] == "retry_failed"


def test_summary_failure_does_not_retry_business_call() -> None:
    history, request_id = _history()

    def invalid_summary(request: ModelRequest) -> ModelResponse:
        assert request.metadata.get("purpose") == "context_compaction"
        return ModelResponse.from_final(" ", finish_reason="stop")

    model = _PlannedModel([_overflow(), invalid_summary])
    trace = AgentTraceCollector()

    with pytest.raises(AgentRuntimeError):
        _run(
            AgentRuntime(model, _registry(), limits=_limits()),
            history,
            request_id,
            trace_collector=trace,
        )

    assert len(model.requests) == 2
    assert len(history.compaction_records) == 0
    assert trace.snapshot()["overflow_recoveries"][0]["status"] == "compaction_failed"


def test_summary_context_overflow_does_not_recurse_recovery() -> None:
    history, request_id = _history()
    model = _PlannedModel([_overflow(), _overflow()])
    trace = AgentTraceCollector()

    with pytest.raises(ModelContextWindowExceeded):
        _run(
            AgentRuntime(model, _registry(), limits=_limits()),
            history,
            request_id,
            trace_collector=trace,
        )

    assert len(model.requests) == 2
    assert len(history.compaction_records) == 0
    assert trace.snapshot()["overflow_recoveries"][0]["status"] == "compaction_failed"


def test_cancellation_before_overflow_compaction_stops_without_retry() -> None:
    history, request_id = _history()
    token = CancellationToken()

    def overflow_after_cancel(request: ModelRequest) -> ModelResponse:
        token.cancel()
        return _overflow()(request)

    model = _PlannedModel([overflow_after_cancel])
    trace = AgentTraceCollector()

    with pytest.raises(AgentCancelledError):
        _run(
            AgentRuntime(model, _registry(), limits=_limits()),
            history,
            request_id,
            cancellation_token=token,
            trace_collector=trace,
        )

    assert len(model.requests) == 1
    assert trace.snapshot()["overflow_recoveries"][0]["status"] == "cancelled"
    assert history.compaction_records == ()


def test_overflow_recovery_is_disabled_without_context_window() -> None:
    history, request_id = _history()
    model = _PlannedModel([_overflow()])

    with pytest.raises(ModelContextWindowExceeded):
        _run(
            AgentRuntime(model, _registry(), limits=_limits(context_window_tokens=None)),
            history,
            request_id,
        )

    assert len(model.requests) == 1


def test_other_provider_error_does_not_start_overflow_recovery() -> None:
    history, request_id = _history()

    def provider_failure(request: ModelRequest) -> ModelResponse:
        raise ModelProviderError("provider unavailable")

    model = _PlannedModel([provider_failure])
    trace = AgentTraceCollector()

    with pytest.raises(ModelProviderError):
        _run(
            AgentRuntime(model, _registry(), limits=_limits()),
            history,
            request_id,
            trace_collector=trace,
        )

    assert len(model.requests) == 1
    assert "overflow_recoveries" not in trace.snapshot()


def test_deadline_during_overflow_compaction_uses_original_execution_deadline() -> None:
    history, request_id = _history()

    class SlowSummaryModel:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            if len(self.requests) == 1:
                return _overflow()(request)
            await asyncio.sleep(0.05)
            return ModelResponse.from_final("too late", finish_reason="stop")

    model = SlowSummaryModel()
    trace = AgentTraceCollector()
    limits = _limits().model_copy(update={"deadline_seconds": 0.02})

    result = _run(
        AgentRuntime(model, _registry(), limits=limits),
        history,
        request_id,
        trace_collector=trace,
    )

    assert "execution stopped before" in result.content  # type: ignore[union-attr]
    assert len(model.requests) == 2
    assert trace.snapshot()["overflow_recoveries"][0]["status"] == "deadline_exceeded"
    assert history.compaction_records == ()


class _StreamingOverflowModel:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def stream(self, request: ModelRequest):
        self.requests.append(request)
        index = len(self.requests)

        async def emit():
            if index == 1:
                yield ModelTextDelta(text="failed partial")
                raise ModelContextWindowExceeded(
                    cause=ModelContextWindowError(
                        provider_code="context_length_exceeded",
                        status_code=None,
                    ),
                    provider_code="context_length_exceeded",
                    status_code=None,
                )
            if index == 2:
                assert request.metadata.get("purpose") == "context_compaction"
                yield ModelResponse.from_final("compressed background", finish_reason="stop")
            elif index == 3:
                yield ModelResponse.from_final("execution", finish_reason="stop")
            else:
                yield ModelResponse.from_final("answer", finish_reason="stop")

        return emit()


def test_stream_partial_text_is_archived_separately_from_success() -> None:
    history, request_id = _history()
    model = _StreamingOverflowModel()
    trace = AgentTraceCollector()
    events: list[object] = []

    async def sink(event: object) -> None:
        events.append(event)

    result = _run(
        AgentRuntime(model, _registry(), limits=_limits()),
        history,
        request_id,
        trace_collector=trace,
        event_sink=sink,
    )

    assert result.content == "answer"  # type: ignore[union-attr]
    assert not any(
        isinstance(event, TextDelta) and event.text == "failed partial" for event in events
    )
    attempt = trace.snapshot()["steps"][0]["failed_model_attempts"][0]
    assert attempt["streamed_text"] == ["failed partial"]
    assert "streamed_text" not in trace.snapshot()["steps"][0]
