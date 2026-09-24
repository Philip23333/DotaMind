from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from uuid import uuid4

import httpx
import pytest

from app.vnext.agent.errors import (
    AgentCancelledError,
    AgentDeadlineExceeded,
    CompactionFailedError,
    ModelProviderError,
)
from app.vnext.agent.events import AgentFailed, CompactionFailed
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime, CancellationToken, _Deadline
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.errors import ModelTransientError
from app.vnext.llm.openai_compatible import (
    OpenAICompatibleModelClient,
    ProviderHTTPError,
    TransientProviderHTTPError,
)
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools.registry import ToolRegistry
from tests.vnext.fakes import ScriptedModelClient


def _request() -> ModelRequest:
    return ModelRequest(messages=[UserMessage(content="request")])


def _adapter(handler: Callable[[httpx.Request], httpx.Response]) -> OpenAICompatibleModelClient:
    return OpenAICompatibleModelClient(
        api_key="test-key",
        base_url="https://provider.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )


def test_http_statuses_are_classified_without_adapter_retries() -> None:
    for status in (408, 500, 502, 503, 504):
        client = _adapter(
            lambda request, status=status: httpx.Response(
                status,
                json={"error": {"message": "temporary"}},
                request=request,
            )
        )

        async def call(client: OpenAICompatibleModelClient = client) -> None:
            await asyncio.wait_for(client.complete(_request()), timeout=1)

        with pytest.raises(TransientProviderHTTPError) as error:
            asyncio.run(call())
        assert isinstance(error.value, ModelTransientError)
        assert isinstance(error.value, ProviderHTTPError)
        assert error.value.status_code == status


@pytest.mark.parametrize(
    "error_object",
    [
        {"code": "insufficient_quota"},
        {"type": "quota_exceeded"},
        {"code": "billing_hard_limit_reached"},
    ],
)
def test_quota_429_is_not_transient(error_object: dict[str, str]) -> None:
    client = _adapter(
        lambda request: httpx.Response(429, json={"error": error_object}, request=request)
    )

    async def call() -> None:
        await asyncio.wait_for(client.complete(_request()), timeout=1)

    with pytest.raises(ProviderHTTPError) as error:
        asyncio.run(call())
    assert not isinstance(error.value, ModelTransientError)
    assert error.value.status_code == 429


def test_ordinary_429_is_transient_for_streaming_calls() -> None:
    client = _adapter(
        lambda request: httpx.Response(
            429,
            json={"error": {"message": "insufficient_quota"}},
            request=request,
        )
    )

    async def call() -> None:
        async for _item in client.stream(_request()):
            pass

    with pytest.raises(TransientProviderHTTPError) as error:
        asyncio.run(asyncio.wait_for(call(), timeout=1))
    assert error.value.status_code == 429


@pytest.mark.parametrize(
    "error_type",
    [httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError],
)
def test_transport_failures_are_provider_neutral_transient_errors(
    error_type: type[Exception],
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise error_type("network body must not be exposed", request=request)

    client = _adapter(fail)

    async def call() -> None:
        await asyncio.wait_for(client.complete(_request()), timeout=1)

    with pytest.raises(ModelTransientError) as error:
        asyncio.run(call())
    assert type(error.value.__cause__) is error_type
    assert "network body" not in str(error.value)


def _history_with_old_context() -> tuple[SessionExecutionHistory, object]:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(
        request_id,
        "current request",
        initial_messages=[
            UserMessage(content="older request"),
            FinalMessage(content="older answer"),
            UserMessage(content="current request"),
        ],
    )
    return history, request_id


def _history_with_split_turn() -> tuple[SessionExecutionHistory, object, int]:
    history, request_id = _history_with_old_context()
    current = UserMessage(content="current request")
    call = ToolCall(id="old-tool-call", name="lookup", arguments={"query": "synthetic"})
    group = AssistantMessage(tool_calls=[call])
    result = ToolResultMessage(tool_call_id=call.id, content={"value": "synthetic evidence"})
    recent = AssistantMessage(content="recent progress")
    final = FinalMessage(content="recent final")
    history.set_effective(
        [
            UserMessage(content="older request"),
            FinalMessage(content="older answer"),
            current,
            AssistantMessage(content="early progress"),
            group,
            result,
            recent,
            final,
        ]
    )
    recent_tokens = sum(
        (len(message.model_dump_json().encode("utf-8")) + 1) // 2
        for message in (group, result, recent, final)
    )
    return history, request_id, recent_tokens


def _runtime(model: object, *, retries: int = 1) -> AgentRuntime:
    return AgentRuntime(
        model,  # type: ignore[arg-type]
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=2, compaction_max_retries=retries),
    )


def _run_compaction(
    runtime: AgentRuntime,
    history: SessionExecutionHistory,
    request_id: object,
    *,
    trace: AgentTraceCollector | None = None,
    token: CancellationToken | None = None,
    deadline: _Deadline | None = None,
    recent_tokens: int = 1,
) -> bool:
    async def run() -> bool:
        return await asyncio.wait_for(
            runtime._compact_session_history(
                execution_history=history,
                request_id=request_id,
                token=token or CancellationToken(),
                deadline=deadline or _Deadline(2),
                step=1,
                recent_history_tokens=recent_tokens,
                max_input_bytes=100_000,
                trace_collector=trace,
            ),
            timeout=1,
        )

    return asyncio.run(run())


def _fast_retry_wait(
    runtime: AgentRuntime,
    *,
    delays: list[float],
    on_wait: Callable[[], None] | None = None,
) -> None:
    original = runtime._await_controlled

    async def controlled(awaitable, token, deadline):
        if inspect.iscoroutine(awaitable) and awaitable.cr_code.co_name == "sleep":
            assert awaitable.cr_frame is not None
            delays.append(awaitable.cr_frame.f_locals["delay"])
            awaitable.close()
            if on_wait is not None:
                on_wait()
            runtime._check_controls(token, deadline)
            return None
        return await original(awaitable, token, deadline)

    runtime._await_controlled = controlled  # type: ignore[method-assign]


def _transient_failure() -> ModelProviderError:
    cause = ModelTransientError("fixed transport failure")
    return ModelProviderError("safe provider failure", cause=cause)


def test_summary_503_then_success_retries_same_request_and_commits_once() -> None:
    history, request_id = _history_with_old_context()
    model = ScriptedModelClient(
        [
            _transient_failure(),
            ModelResponse.from_final(
                "compressed history",
                finish_reason="stop",
                usage={"completion_tokens": 4},
            ),
        ]
    )
    runtime = _runtime(model)
    delays: list[float] = []
    _fast_retry_wait(runtime, delays=delays)
    trace = AgentTraceCollector()

    assert _run_compaction(runtime, history, request_id, trace=trace)

    assert len(model.requests) == 2
    assert model.requests[0] == model.requests[1]
    assert delays == [1]
    assert len(history.compaction_records) == 1
    snapshot = trace.snapshot()
    assert [call["attempt"] for call in snapshot["compaction_calls"]] == [1, 2]
    assert snapshot["compaction_calls"][0]["usage"] == {}
    assert snapshot["compaction_calls"][1]["usage"] == {"completion_tokens": 4}
    assert snapshot["compaction_retries"] == [
        {
            "step": 1,
            "kind": "history",
            "failed_attempt": 1,
            "next_attempt": 2,
            "delay_seconds": 1,
            "error_code": "model_provider_error",
        }
    ]


def test_http_503_then_sse_success_is_retried_by_runtime_once() -> None:
    history, request_id = _history_with_old_context()
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.read())
        if len(seen) == 1:
            return httpx.Response(503, json={"error": {"message": "retry"}}, request=request)
        chunk = {
            "choices": [
                {
                    "delta": {"role": "assistant", "content": "adapter summary"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"completion_tokens": 6},
        }
        body = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=body,
            request=request,
        )

    model = _adapter(handler)
    runtime = _runtime(model)
    delays: list[float] = []
    _fast_retry_wait(runtime, delays=delays)
    trace = AgentTraceCollector()

    assert _run_compaction(runtime, history, request_id, trace=trace)

    assert len(seen) == 2
    assert seen[0] == seen[1]
    assert delays == [1]
    assert len(history.compaction_records) == 1
    assert [call["status"] for call in trace.snapshot()["compaction_calls"]] == [
        "failed",
        "generated",
    ]
    assert trace.snapshot()["compaction_calls"][1]["usage"] == {"completion_tokens": 6}


def test_first_summary_success_has_no_retry_delay() -> None:
    history, request_id = _history_with_old_context()
    model = ScriptedModelClient([ModelResponse.from_final("summary", finish_reason="stop")])
    runtime = _runtime(model)
    delays: list[float] = []
    _fast_retry_wait(runtime, delays=delays)

    assert _run_compaction(runtime, history, request_id)
    assert len(model.requests) == 1
    assert delays == []


def test_second_summary_segment_retries_without_regenerating_first() -> None:
    history, request_id, recent_tokens = _history_with_split_turn()
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("history summary", finish_reason="stop"),
            _transient_failure(),
            ModelResponse.from_final("turn summary", finish_reason="stop"),
        ]
    )
    runtime = _runtime(model)
    delays: list[float] = []
    _fast_retry_wait(runtime, delays=delays)
    trace = AgentTraceCollector()

    assert _run_compaction(
        runtime,
        history,
        request_id,
        trace=trace,
        recent_tokens=recent_tokens,
    )

    assert [request.metadata["compaction_kind"] for request in model.requests] == [
        "history",
        "turn_prefix",
        "turn_prefix",
    ]
    assert model.requests[1] == model.requests[2]
    assert delays == [1]
    assert len(history.compaction_records) == 1
    assert [call["kind"] for call in trace.snapshot()["compaction_calls"]] == [
        "history",
        "turn_prefix",
        "turn_prefix",
    ]


def test_failed_second_summary_segment_discards_first_candidate() -> None:
    history, request_id, recent_tokens = _history_with_split_turn()
    model = ScriptedModelClient(
        [
            ModelResponse.from_final(
                "uncommitted history candidate",
                finish_reason="stop",
                usage={"completion_tokens": 5},
            ),
            _transient_failure(),
            _transient_failure(),
        ]
    )
    runtime = _runtime(model)
    _fast_retry_wait(runtime, delays=[])
    before = history.context_snapshot()
    trace = AgentTraceCollector()

    with pytest.raises(CompactionFailedError) as error:
        _run_compaction(
            runtime,
            history,
            request_id,
            trace=trace,
            recent_tokens=recent_tokens,
        )

    assert error.value.summary_kind == "turn_prefix"
    assert error.value.attempt_count == 2
    assert history.context_snapshot() == before
    assert history.compaction_records == ()
    assert [call["kind"] for call in trace.snapshot()["compaction_calls"]] == [
        "history",
        "turn_prefix",
        "turn_prefix",
    ]
    assert trace.snapshot()["compaction_calls"][0]["usage"] == {"completion_tokens": 5}


def test_retry_exhaustion_preserves_original_session_state() -> None:
    history, request_id = _history_with_old_context()
    model = ScriptedModelClient([_transient_failure(), _transient_failure()])
    runtime = _runtime(model)
    _fast_retry_wait(runtime, delays=[])
    before = history.context_snapshot()
    trace = AgentTraceCollector()

    with pytest.raises(CompactionFailedError) as error:
        _run_compaction(runtime, history, request_id, trace=trace)

    assert error.value.reason_code == "transient_retries_exhausted"
    assert error.value.summary_kind == "history"
    assert error.value.attempt_count == 2
    assert len(model.requests) == 2
    assert history.context_snapshot() == before
    assert history.compaction_records == ()
    assert len(trace.snapshot()["compaction_calls"]) == 2
    assert len(trace.snapshot()["compaction_retries"]) == 1


def test_zero_retries_means_one_actual_summary_call() -> None:
    history, request_id = _history_with_old_context()
    model = ScriptedModelClient([_transient_failure()])
    runtime = _runtime(model, retries=0)
    delays: list[float] = []
    _fast_retry_wait(runtime, delays=delays)

    with pytest.raises(CompactionFailedError) as error:
        _run_compaction(runtime, history, request_id)

    assert error.value.attempt_count == 1
    assert error.value.reason_code == "transient_retries_exhausted"
    assert len(model.requests) == 1
    assert delays == []


def test_three_retries_use_fixed_bounded_backoff_schedule() -> None:
    history, request_id = _history_with_old_context()
    model = ScriptedModelClient([_transient_failure() for _ in range(4)])
    runtime = _runtime(model, retries=3)
    delays: list[float] = []
    _fast_retry_wait(runtime, delays=delays)
    trace = AgentTraceCollector()

    with pytest.raises(CompactionFailedError) as error:
        _run_compaction(runtime, history, request_id, trace=trace)

    assert error.value.attempt_count == 4
    assert len(model.requests) == 4
    assert delays == [1, 2, 4]
    assert [item["delay_seconds"] for item in trace.snapshot()["compaction_retries"]] == [
        1,
        2,
        4,
    ]


@pytest.mark.parametrize(
    "response",
    [
        ModelResponse.from_final("truncated", finish_reason="length"),
        ModelResponse.from_final(" ", finish_reason="stop"),
        ModelResponse.from_assistant(
            AssistantMessage(tool_calls=[ToolCall(id="call", name="tool", arguments={})]),
            finish_reason="tool_calls",
        ),
    ],
)
def test_invalid_summary_responses_are_never_retried(response: ModelResponse) -> None:
    history, request_id = _history_with_old_context()
    model = ScriptedModelClient([response])
    runtime = _runtime(model, retries=3)
    delays: list[float] = []
    _fast_retry_wait(runtime, delays=delays)

    with pytest.raises(CompactionFailedError):
        _run_compaction(runtime, history, request_id)

    assert len(model.requests) == 1
    assert delays == []
    assert history.compaction_records == ()


def test_permanent_provider_error_is_not_retried() -> None:
    history, request_id = _history_with_old_context()
    permanent = ModelProviderError(
        "provider rejected request",
        cause=ProviderHTTPError(401, "secret"),
    )
    model = ScriptedModelClient([permanent])
    runtime = _runtime(model, retries=3)
    delays: list[float] = []
    _fast_retry_wait(runtime, delays=delays)

    with pytest.raises(CompactionFailedError) as error:
        _run_compaction(runtime, history, request_id)

    assert error.value.reason_code == "model_provider_error"
    assert len(model.requests) == 1
    assert delays == []


@pytest.mark.parametrize("control", ["cancel", "deadline"])
def test_wait_control_stops_before_scheduling_another_attempt(control: str) -> None:
    history, request_id = _history_with_old_context()
    model = ScriptedModelClient([_transient_failure()])
    runtime = _runtime(model)
    token = CancellationToken()
    deadline = _Deadline(2)

    def interrupt() -> None:
        if control == "cancel":
            token.cancel()
        else:
            deadline.expires_at = deadline.started - 1

    delays: list[float] = []
    _fast_retry_wait(runtime, delays=delays, on_wait=interrupt)
    trace = AgentTraceCollector()

    with pytest.raises(AgentCancelledError if control == "cancel" else AgentDeadlineExceeded):
        _run_compaction(
            runtime,
            history,
            request_id,
            token=token,
            deadline=deadline,
            trace=trace,
        )

    assert len(model.requests) == 1
    assert delays == [1]
    assert len(trace.snapshot()["compaction_retries"]) == 1
    assert len(trace.snapshot()["compaction_calls"]) == 1
    assert history.compaction_records == ()


def test_revision_change_during_retry_rejects_commit() -> None:
    history, request_id = _history_with_old_context()
    model = ScriptedModelClient(
        [
            _transient_failure(),
            ModelResponse.from_final("stale candidate", finish_reason="stop"),
        ]
    )
    runtime = _runtime(model)
    delays: list[float] = []

    def change_revision() -> None:
        history.set_effective(history.effective_messages())

    _fast_retry_wait(runtime, delays=delays, on_wait=change_revision)
    trace = AgentTraceCollector()

    with pytest.raises(CompactionFailedError) as error:
        _run_compaction(runtime, history, request_id, trace=trace)

    assert error.value.reason_code == "stale_context_revision"
    assert error.value.summary_kind is None
    assert error.value.attempt_count == 0
    assert len(model.requests) == 2
    assert history.compaction_records == ()
    assert len(trace.snapshot()["compaction_calls"]) == 2


def test_outer_runtime_publishes_one_compaction_failure_then_agent_failure() -> None:
    history, request_id = _history_with_old_context()
    model = ScriptedModelClient([ModelResponse.from_final("partial", finish_reason="length")])
    runtime = AgentRuntime(
        model,  # type: ignore[arg-type]
        ToolRegistry(),
        limits=AgentLimits(
            deadline_seconds=2,
            compaction_max_retries=3,
            compaction_keep_recent_tokens=1,
            compaction_max_input_bytes=100_000,
        ),
    )
    events: list[object] = []
    trace = AgentTraceCollector()

    async def run() -> None:
        async for _event in runtime.run_stream(
            history.effective_messages(),
            execution_history=history,
            request_id=request_id,
            compact_before_steps=(1,),
            event_sink=lambda event: events.append(event),
            trace_collector=trace,
        ):
            pass

    with pytest.raises(CompactionFailedError):
        asyncio.run(asyncio.wait_for(run(), timeout=1))

    compaction_events = [event for event in events if isinstance(event, CompactionFailed)]
    assert len(compaction_events) == 1
    assert compaction_events[0].model_dump(exclude={"timestamp"}) == CompactionFailed(
        step=1,
        trigger="explicit",
        stage="execution",
        summary_kind="history",
        reason_code="summary_output_truncated",
        attempt_count=1,
    ).model_dump(exclude={"timestamp"})
    failed = [event for event in events if isinstance(event, AgentFailed)]
    assert len(failed) == 1
    assert failed[0].details["reason_code"] == "summary_output_truncated"
    assert len(model.requests) == 1
    assert history.compaction_records == ()
    assert len(trace.snapshot()["compaction_failures"]) == 1


def test_summary_context_overflow_is_not_recursively_recovered() -> None:
    history, request_id = _history_with_old_context()
    overflow = ModelProviderError("provider context limit", cause=RuntimeError("context"))
    # A non-transient provider classification must fail without creating an
    # additional compaction or business retry.
    model = ScriptedModelClient([overflow])
    runtime = _runtime(model, retries=3)

    with pytest.raises(CompactionFailedError) as error:
        _run_compaction(runtime, history, request_id)

    assert error.value.reason_code == "model_provider_error"
    assert len(model.requests) == 1
    assert history.compaction_records == ()


def test_transient_business_model_failure_is_not_retried() -> None:
    history, request_id = _history_with_old_context()
    model = ScriptedModelClient([ModelTransientError("transient business failure")])
    runtime = _runtime(model)
    trace = AgentTraceCollector()

    async def run() -> None:
        await asyncio.wait_for(
            runtime.run(
                history.effective_messages(),
                execution_history=history,
                request_id=request_id,
                trace_collector=trace,
            ),
            timeout=1,
        )

    with pytest.raises(ModelProviderError):
        asyncio.run(run())

    assert len(model.requests) == 1
    assert model.requests[0].metadata == {}
    assert "compaction_calls" not in trace.snapshot()
    assert "compaction_retries" not in trace.snapshot()
