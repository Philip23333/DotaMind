from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.vnext.agent.errors import (
    AgentCancelledError,
    AgentDeadlineExceeded,
    ModelProtocolError,
    ModelProviderError,
)
from app.vnext.agent.evidence_summary_lifecycle import (
    CompactionSummaryError,
    build_compaction_request,
)
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import (
    AgentRuntime,
    CancellationToken,
    _Deadline,
)
from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelRequest,
    ModelResponse,
    ModelTextDelta,
    ToolCall,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools.registry import ToolRegistry
from tests.vnext.fakes import ScriptedModelClient, ScriptedStreamingModelClient


def _request() -> ModelRequest:
    return build_compaction_request(
        previous_summary="previous summary",
        current_user_message=UserMessage(content="current question"),
        prefix_messages=[UserMessage(content="old history")],
        current_user_prefix_index=None,
        max_input_bytes=100_000,
        max_output_tokens=128,
    )


def _runtime(
    model: object,
    *,
    task_state_coordinator: TaskStateCoordinator | None = None,
) -> AgentRuntime:
    return AgentRuntime(
        model,  # type: ignore[arg-type]
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=2),
        task_state_coordinator=task_state_coordinator,
    )


def _call(
    runtime: AgentRuntime,
    request: ModelRequest,
    *,
    token: CancellationToken | None = None,
    deadline: _Deadline | None = None,
    step: int = 4,
    max_summary_bytes: int = 10_000,
    trace: AgentTraceCollector | None = None,
) -> object:
    return asyncio.run(
        runtime._generate_compaction_summary(
            request,
            token=token or CancellationToken(),
            deadline=deadline or _Deadline(2),
            step=step,
            max_summary_bytes=max_summary_bytes,
            trace_collector=trace,
        )
    )


def test_non_streaming_compaction_call_returns_validated_result() -> None:
    usage = {"prompt_tokens": 20, "completion_tokens": 7, "nested": {"x": 1}}
    model = ScriptedModelClient(
        [ModelResponse.from_final("原始摘要", finish_reason="stop", usage=usage)]
    )
    trace = AgentTraceCollector()

    result = _call(_runtime(model), _request(), trace=trace)

    assert result.summary == "原始摘要"
    assert result.usage == usage
    assert result.duration_seconds >= 0
    assert len(model.requests) == 1
    assert model.requests[0].max_output_tokens == 128
    assert model.requests[0].metadata == {"purpose": "context_compaction"}
    assert trace.snapshot()["compaction_calls"] == [
        {
            "step": 4,
            "status": "generated",
            "duration_seconds": result.duration_seconds,
            "usage": usage,
            "error_code": None,
        }
    ]
    assert trace.snapshot()["steps"] == []


def test_compaction_call_deep_copies_provider_usage() -> None:
    usage = {"nested": {"count": 1}}
    model = ScriptedModelClient(
        [ModelResponse.from_final("summary", finish_reason="stop", usage=usage)]
    )

    result = _call(_runtime(model), _request())
    usage["nested"]["count"] = 99
    result.usage["nested"]["count"] = 3

    assert model.requests == [model.requests[0]]
    assert result.usage == {"nested": {"count": 3}}


def test_streaming_compaction_call_consumes_summary_without_product_events() -> None:
    model = ScriptedStreamingModelClient(
        [
            [
                ModelTextDelta(text="internal summary"),
                ModelResponse.from_final("streamed summary", finish_reason="stop"),
            ]
        ]
    )
    events: list[object] = []
    runtime = AgentRuntime(
        model,  # type: ignore[arg-type]
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=2),
        event_sink=lambda event: events.append(event),
    )
    trace = AgentTraceCollector()

    result = _call(runtime, _request(), trace=trace, step=9)

    assert result.summary == "streamed summary"
    assert events == []
    assert trace.snapshot()["steps"] == []
    assert trace.snapshot()["compaction_calls"][0]["status"] == "generated"


def test_compaction_call_rejects_cancelled_token_before_model_call() -> None:
    token = CancellationToken()
    token.cancel()
    model = ScriptedModelClient([])
    trace = AgentTraceCollector()

    with pytest.raises(AgentCancelledError):
        _call(_runtime(model), _request(), token=token, trace=trace)

    assert model.requests == []
    assert trace.snapshot()["compaction_calls"][0]["status"] == "cancelled"


def test_compaction_call_rejects_expired_deadline_before_model_call() -> None:
    model = ScriptedModelClient([])
    trace = AgentTraceCollector()

    with pytest.raises(AgentDeadlineExceeded):
        _call(_runtime(model), _request(), deadline=_Deadline(0), trace=trace)

    assert model.requests == []
    assert trace.snapshot()["compaction_calls"][0]["status"] == "deadline_exceeded"


def test_compaction_call_cancels_an_in_flight_model_request() -> None:
    class WaitingModel:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cleaned = False
            self.requests: list[ModelRequest] = []

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            self.started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cleaned = True
            raise AssertionError("unreachable")

    async def exercise() -> tuple[WaitingModel, AgentTraceCollector]:
        model = WaitingModel()
        token = CancellationToken()
        trace = AgentTraceCollector()
        task = asyncio.create_task(
            _runtime(model)._generate_compaction_summary(
                _request(),
                token=token,
                deadline=_Deadline(2),
                step=3,
                max_summary_bytes=10_000,
                trace_collector=trace,
            )
        )
        await model.started.wait()
        token.cancel()
        with pytest.raises(AgentCancelledError):
            await task
        return model, trace

    model, trace = asyncio.run(exercise())

    assert model.cleaned is True
    assert trace.snapshot()["compaction_calls"][0]["usage"] == {}
    assert trace.snapshot()["compaction_calls"][0]["status"] == "cancelled"


def test_compaction_call_uses_remaining_shared_deadline() -> None:
    class WaitingModel:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    async def exercise() -> tuple[WaitingModel, AgentTraceCollector]:
        model = WaitingModel()
        trace = AgentTraceCollector()
        deadline = _Deadline(0.02)
        await asyncio.sleep(0.005)
        with pytest.raises(AgentDeadlineExceeded):
            await asyncio.wait_for(
                _runtime(model)._generate_compaction_summary(
                    _request(),
                    token=CancellationToken(),
                    deadline=deadline,
                    step=5,
                    max_summary_bytes=10_000,
                    trace_collector=trace,
                ),
                timeout=1,
            )
        return model, trace

    model, trace = asyncio.run(exercise())

    assert len(model.requests) == 1
    assert trace.snapshot()["compaction_calls"][0]["status"] == "deadline_exceeded"


def test_returned_response_is_rejected_when_summary_validation_fails() -> None:
    usage = {"completion_tokens": 3}
    model = ScriptedModelClient(
        [ModelResponse.from_final(" ", finish_reason="stop", usage=usage)]
    )
    trace = AgentTraceCollector()

    with pytest.raises(CompactionSummaryError) as error:
        _call(_runtime(model), _request(), trace=trace)

    assert error.value.code == "empty_summary"
    assert trace.snapshot()["compaction_calls"][0]["usage"] == usage


def test_compaction_call_rejects_summary_that_exceeds_byte_budget() -> None:
    model = ScriptedModelClient(
        [ModelResponse.from_final("中文摘要", finish_reason="stop", usage={"n": 1})]
    )
    trace = AgentTraceCollector()

    with pytest.raises(CompactionSummaryError) as error:
        _call(_runtime(model), _request(), max_summary_bytes=1, trace=trace)

    assert error.value.code == "summary_output_too_large"
    assert trace.snapshot()["compaction_calls"][0]["usage"] == {"n": 1}


def test_cancellation_after_provider_return_does_not_deliver_a_summary() -> None:
    class CancelOnResponseModel:
        def __init__(self, token: CancellationToken) -> None:
            self.token = token
            self.requests: list[ModelRequest] = []
            self.response = ModelResponse.from_final(
                "valid summary",
                finish_reason="stop",
                usage={"completion_tokens": 7, "details": {"count": 1}},
            )

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            self.token.cancel()
            return self.response

    async def exercise() -> tuple[CancelOnResponseModel, AgentTraceCollector]:
        token = CancellationToken()
        model = CancelOnResponseModel(token)
        trace = AgentTraceCollector()
        with pytest.raises(AgentCancelledError):
            await _runtime(model)._generate_compaction_summary(
                _request(),
                token=token,
                deadline=_Deadline(2),
                step=6,
                max_summary_bytes=10_000,
                trace_collector=trace,
            )
        return model, trace

    model, trace = asyncio.run(exercise())

    assert len(model.requests) == 1
    assert trace.snapshot()["compaction_calls"][0]["usage"] == {
        "completion_tokens": 7,
        "details": {"count": 1},
    }
    model.response.usage["details"]["count"] = 99
    assert trace.snapshot()["compaction_calls"][0]["usage"]["details"]["count"] == 1
    assert trace.snapshot()["steps"] == []
    assert trace.snapshot()["compaction_calls"][0]["status"] == "cancelled"


def test_deadline_after_provider_return_preserves_usage_without_a_candidate() -> None:
    class DeadlineAfterResponseModel:
        def __init__(self, deadline: _Deadline) -> None:
            self.deadline = deadline
            self.requests: list[ModelRequest] = []
            self.response = ModelResponse.from_final(
                "valid summary",
                finish_reason="stop",
                usage={"completion_tokens": 8, "details": {"count": 2}},
            )

        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            self.deadline.expires_at = self.deadline.started - 1
            return self.response

    async def exercise() -> tuple[DeadlineAfterResponseModel, AgentTraceCollector]:
        deadline = _Deadline(2)
        model = DeadlineAfterResponseModel(deadline)
        trace = AgentTraceCollector()
        with pytest.raises(AgentDeadlineExceeded):
            await _runtime(model)._generate_compaction_summary(
                _request(),
                token=CancellationToken(),
                deadline=deadline,
                step=7,
                max_summary_bytes=10_000,
                trace_collector=trace,
            )
        return model, trace

    model, trace = asyncio.run(exercise())

    assert len(model.requests) == 1
    assert trace.snapshot()["compaction_calls"] == [
        {
            "step": 7,
            "status": "deadline_exceeded",
            "duration_seconds": trace.snapshot()["compaction_calls"][0][
                "duration_seconds"
            ],
            "usage": {"completion_tokens": 8, "details": {"count": 2}},
            "error_code": "deadline_exceeded",
        }
    ]
    model.response.usage["details"]["count"] = 100
    assert trace.snapshot()["compaction_calls"][0]["usage"]["details"]["count"] == 2


def test_stream_cancellation_after_terminal_response_preserves_usage_and_cleans_up() -> None:
    class StreamingCancelModel:
        def __init__(self, token: CancellationToken) -> None:
            self.token = token
            self.requests: list[ModelRequest] = []
            self.cleaned = False
            self.response = ModelResponse.from_final(
                "streamed summary",
                finish_reason="stop",
                usage={"completion_tokens": 9, "details": {"count": 3}},
            )

        def stream(self, request: ModelRequest):
            self.requests.append(request)

            async def generate():
                try:
                    yield self.response
                    self.token.cancel()
                finally:
                    self.cleaned = True

            return generate()

    async def exercise() -> tuple[StreamingCancelModel, AgentTraceCollector]:
        token = CancellationToken()
        model = StreamingCancelModel(token)
        trace = AgentTraceCollector()
        with pytest.raises(AgentCancelledError):
            await asyncio.wait_for(
                _runtime(model)._generate_compaction_summary(
                    _request(),
                    token=token,
                    deadline=_Deadline(2),
                    step=8,
                    max_summary_bytes=10_000,
                    trace_collector=trace,
                ),
                timeout=1,
            )
        return model, trace

    model, trace = asyncio.run(exercise())

    assert model.cleaned is True
    assert trace.snapshot()["compaction_calls"][0]["usage"] == {
        "completion_tokens": 9,
        "details": {"count": 3},
    }
    assert trace.snapshot()["steps"] == []
    assert trace.snapshot()["compaction_calls"][0]["status"] == "cancelled"


def test_stream_deadline_after_terminal_response_preserves_usage_and_cleans_up() -> None:
    class StreamingDeadlineModel:
        def __init__(self, deadline: _Deadline) -> None:
            self.deadline = deadline
            self.requests: list[ModelRequest] = []
            self.cleaned = False
            self.response = ModelResponse.from_final(
                "streamed summary",
                finish_reason="stop",
                usage={"completion_tokens": 10, "details": {"count": 4}},
            )

        def stream(self, request: ModelRequest):
            self.requests.append(request)

            async def generate():
                try:
                    yield self.response
                    self.deadline.expires_at = self.deadline.started - 1
                finally:
                    self.cleaned = True

            return generate()

    async def exercise() -> tuple[StreamingDeadlineModel, AgentTraceCollector]:
        deadline = _Deadline(2)
        model = StreamingDeadlineModel(deadline)
        trace = AgentTraceCollector()
        with pytest.raises(AgentDeadlineExceeded):
            await asyncio.wait_for(
                _runtime(model)._generate_compaction_summary(
                    _request(),
                    token=CancellationToken(),
                    deadline=deadline,
                    step=9,
                    max_summary_bytes=10_000,
                    trace_collector=trace,
                ),
                timeout=1,
            )
        return model, trace

    model, trace = asyncio.run(exercise())

    assert model.cleaned is True
    assert trace.snapshot()["compaction_calls"][0]["usage"] == {
        "completion_tokens": 10,
        "details": {"count": 4},
    }
    assert trace.snapshot()["compaction_calls"][0]["status"] == "deadline_exceeded"


@pytest.mark.parametrize(
    ("response", "error_code"),
    [
        (ModelResponse.from_final("summary", finish_reason="length"), "summary_output_truncated"),
        (
            ModelResponse.from_final("summary", finish_reason="tool_calls"),
            "summary_completion_unconfirmed",
        ),
        (
            ModelResponse(
                message=AssistantMessage(
                    tool_calls=[ToolCall(id="call-1", name="lookup", arguments={})]
                ),
                finish_reason="stop",
            ),
            "invalid_summary_response",
        ),
    ],
)
def test_compaction_call_preserves_summary_response_validation_errors(
    response: ModelResponse,
    error_code: str,
) -> None:
    model = ScriptedModelClient([response])
    trace = AgentTraceCollector()

    with pytest.raises(CompactionSummaryError) as error:
        _call(_runtime(model), _request(), trace=trace)

    assert error.value.code == error_code
    assert len(model.requests) == 1
    assert trace.snapshot()["compaction_calls"][0]["status"] == "failed"


def test_compaction_call_preserves_provider_failure_classification() -> None:
    model = ScriptedModelClient([ModelProviderError("provider unavailable")])
    trace = AgentTraceCollector()

    with pytest.raises(ModelProviderError):
        _call(_runtime(model), _request(), trace=trace)

    assert trace.snapshot()["compaction_calls"][0]["error_code"] == "model_provider_error"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda request: request.model_copy(update={"tools": [object()]}),
        lambda request: request.model_copy(update={"step": 1}),
        lambda request: request.model_copy(update={"max_output_tokens": None}),
        lambda request: request.model_copy(update={"metadata": {"purpose": "other"}}),
    ],
)
def test_compaction_call_rejects_invalid_request_shape_without_model_call(
    mutate,
) -> None:
    model = ScriptedModelClient([])
    trace = AgentTraceCollector()

    with pytest.raises(ModelProtocolError):
        _call(_runtime(model), mutate(_request()), trace=trace)

    assert model.requests == []
    assert trace.snapshot()["compaction_calls"][0]["status"] == "failed"


def test_compaction_call_rejects_invalid_summary_budget_without_model_call() -> None:
    model = ScriptedModelClient([])

    with pytest.raises(CompactionSummaryError) as error:
        _call(_runtime(model), _request(), max_summary_bytes=True)

    assert error.value.code == "invalid_summary_budget"
    assert model.requests == []


def test_compaction_call_does_not_reset_task_or_session_state() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(
        request_id,
        "current question",
        initial_messages=[
            UserMessage(content="old question"),
            UserMessage(content="current question"),
        ],
    )
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "first", "objective": "First"},
            {"key": "second", "objective": "Second"},
        ]
    )
    before_effective = history.effective_messages()
    before_records = history.records
    before_locators = history.artifact_locators
    before_plan = coordinator.plan_snapshot()
    model = ScriptedModelClient(
        [ModelResponse.from_final("summary", finish_reason="stop")]
    )

    _call(
        _runtime(model, task_state_coordinator=coordinator),
        _request(),
    )

    assert history.effective_messages() == before_effective
    assert history.records == before_records
    assert history.artifact_locators == before_locators
    assert coordinator.plan_snapshot() == before_plan
