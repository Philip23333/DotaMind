from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.vnext.agent.errors import (
    AgentCancelledError,
    AgentDeadlineExceeded,
    ModelProviderError,
)
from app.vnext.agent.evidence_summary_lifecycle import (
    CompactionSummaryError,
    build_compaction_request,
)
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime, CancellationToken, _Deadline
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.protocol import (
    ModelRequest,
    ModelResponse,
    ModelTextDelta,
    SystemMessage,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry
from tests.vnext.fakes import ScriptedModelClient, ScriptedStreamingModelClient


def _request(step: int = 1) -> ModelRequest:
    return ModelRequest(
        messages=[SystemMessage(content="full system prompt"), UserMessage(content="question")],
        step=step,
        metadata={"source": "test"},
        max_output_tokens=64,
    )


async def _invoke(
    runtime: AgentRuntime,
    request: ModelRequest,
    trace: AgentTraceCollector,
    *,
    token: CancellationToken | None = None,
    deadline: _Deadline | None = None,
    purpose: str = "execution",
) -> ModelResponse:
    response, _, _ = await runtime._invoke_model(
        request,
        purpose=purpose,  # type: ignore[arg-type]
        token=token or CancellationToken(),
        deadline=deadline or _Deadline(2),
        step=request.step or 1,
        trace_collector=trace,
        publish_text=False,
    )
    return response


class _ToolArgs(BaseModel):
    value: int


class _ToolResult(BaseModel):
    value: int


def test_full_recording_captures_the_actual_request_and_response() -> None:
    responses = [
        ModelResponse.from_final("execution", usage={"prompt_tokens": 11}),
        ModelResponse.from_final("answer", usage={"prompt_tokens": 13}),
    ]
    model = ScriptedModelClient(responses)
    trace = AgentTraceCollector(capture_full_calls=True)
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="echo",
            description="Return the input value.",
            input_model=_ToolArgs,
            output_model=_ToolResult,
            handler=lambda args: _ToolResult(value=args.value),
        )
    )
    runtime = AgentRuntime(
        model,
        tools,
        limits=AgentLimits(
            deadline_seconds=2,
            context_window_tokens=100_000,
            context_output_reserve_tokens=2048,
        ),
        system_instruction="runtime-owned system instruction",
    )

    request_id = uuid4()
    history = SessionExecutionHistory()
    history.begin_request(
        request_id,
        "question",
        initial_messages=[UserMessage(content="question")],
    )
    asyncio.run(
        runtime.run(
            [UserMessage(content="question")],
            trace_collector=trace,
            execution_history=history,
            request_id=request_id,
        )
    )

    calls = trace.snapshot()["model_calls"]
    assert [call["purpose"] for call in calls] == ["execution", "primary_answer"]
    assert [call["status"] for call in calls] == ["completed", "completed"]
    assert calls[0]["request"] == model.requests[0].model_dump(mode="json")
    assert calls[1]["request"] == model.requests[1].model_dump(mode="json")
    assert calls[0]["request"]["messages"][0]["content"].startswith(
        "runtime-owned system instruction"
    )
    assert calls[0]["request"]["tools"][0]["name"] == "echo"
    assert calls[0]["request"]["max_output_tokens"] == 2048
    assert calls[1]["request"]["max_output_tokens"] == 2048
    assert calls[0]["response"]["usage"] == {"prompt_tokens": 11}
    assert calls[1]["response"]["message"] == {"role": "final", "content": "answer"}
    assert all(call["duration_seconds"] is not None for call in calls)


def test_same_step_calls_are_independent_and_collectors_do_not_share_records() -> None:
    request = _request()
    first_trace = AgentTraceCollector(capture_full_calls=True)
    second_trace = AgentTraceCollector(capture_full_calls=True)
    response = ModelResponse.from_final("summary", usage={"nested": {"count": 1}})

    first_id = first_trace.model_call_started(request, step=1, purpose="compaction")
    first_trace.model_call_response(first_id, response)
    first_trace.model_call_finished(
        first_id,
        status="completed",
        duration_seconds=0.1,
    )
    second_id = first_trace.model_call_started(request, step=1, purpose="execution")
    first_trace.model_call_finished(
        second_id,
        status="failed",
        duration_seconds=0.2,
    )
    separate_id = second_trace.model_call_started(request, step=1, purpose="degraded_answer")
    second_trace.model_call_finished(
        separate_id,
        status="completed",
        duration_seconds=0.3,
    )

    response.usage["nested"]["count"] = 99
    first_calls = first_trace.snapshot()["model_calls"]
    second_calls = second_trace.snapshot()["model_calls"]
    assert first_id != second_id
    assert separate_id not in {first_id, second_id}
    assert [call["step"] for call in first_calls] == [1, 1]
    assert second_calls[0]["step"] == 1
    assert first_calls[0]["purpose"] == "compaction"
    assert first_calls[0]["response"]["usage"] == {"nested": {"count": 1}}
    assert first_calls[1]["purpose"] == "execution"
    assert first_calls[1]["response"] is None
    assert first_calls[1]["status"] == "failed"
    assert second_calls[0]["purpose"] == "degraded_answer"


def test_recording_hook_failures_do_not_change_model_call_behavior() -> None:
    class BrokenRecording(AgentTraceCollector):
        def model_call_started(self, *_args, **_kwargs):
            raise RuntimeError("recording failure")

        def model_call_response(self, *_args, **_kwargs):
            raise RuntimeError("recording failure")

        def model_call_finished(self, *_args, **_kwargs):
            raise RuntimeError("recording failure")

    model = ScriptedModelClient([ModelResponse.from_final("answer")])
    runtime = AgentRuntime(model, ToolRegistry())
    response = asyncio.run(
        _invoke(runtime, _request(), BrokenRecording(capture_full_calls=True))
    )

    assert response.message.content == "answer"
    assert len(model.requests) == 1


def test_response_and_usage_are_retained_when_cancellation_follows_response() -> None:
    class CancelAfterResponse:
        async def complete(self, _request: ModelRequest) -> ModelResponse:
            token.cancel()
            return ModelResponse.from_final("received", usage={"prompt_tokens": 7})

    token = CancellationToken()
    trace = AgentTraceCollector(capture_full_calls=True)
    runtime = AgentRuntime(CancelAfterResponse(), ToolRegistry())  # type: ignore[arg-type]

    with pytest.raises(AgentCancelledError):
        asyncio.run(_invoke(runtime, _request(), trace, token=token))

    call = trace.snapshot()["model_calls"][0]
    assert call["status"] == "cancelled"
    assert call["response"]["usage"] == {"prompt_tokens": 7}
    assert call["error_type"] == "AgentCancelledError"


def test_streaming_cancellation_retains_partial_text_and_closes_stream() -> None:
    async def exercise() -> tuple[AgentTraceCollector, bool]:
        started = asyncio.Event()
        cleaned = False

        class WaitingStream:
            def stream(self, _request: ModelRequest):
                async def generate():
                    nonlocal cleaned
                    try:
                        yield ModelTextDelta(text="partial answer")
                        started.set()
                        await asyncio.Event().wait()
                    finally:
                        cleaned = True

                return generate()

        token = CancellationToken()
        trace = AgentTraceCollector(capture_full_calls=True)
        runtime = AgentRuntime(WaitingStream(), ToolRegistry())  # type: ignore[arg-type]
        task = asyncio.create_task(_invoke(runtime, _request(), trace, token=token))
        await asyncio.wait_for(started.wait(), timeout=1)
        token.cancel()
        with pytest.raises(AgentCancelledError):
            await asyncio.wait_for(task, timeout=1)
        return trace, cleaned

    trace, cleaned = asyncio.run(exercise())

    call = trace.snapshot()["model_calls"][0]
    assert call["status"] == "cancelled"
    assert call["partial_text"] == "partial answer"
    assert call["response"] is None
    assert cleaned


def test_deadline_and_provider_failures_are_recorded_without_error_text() -> None:
    class WaitingModel:
        async def complete(self, _request: ModelRequest) -> ModelResponse:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    deadline_trace = AgentTraceCollector(capture_full_calls=True)
    deadline_runtime = AgentRuntime(WaitingModel(), ToolRegistry())  # type: ignore[arg-type]
    with pytest.raises(AgentDeadlineExceeded):
        asyncio.run(
            _invoke(
                deadline_runtime,
                _request(),
                deadline_trace,
                deadline=_Deadline(0.01),
            )
        )
    deadline_call = deadline_trace.snapshot()["model_calls"][0]
    assert deadline_call["status"] == "deadline"
    assert deadline_call["error_code"] == "deadline_exceeded"

    provider_trace = AgentTraceCollector(capture_full_calls=True)
    provider_runtime = AgentRuntime(
        ScriptedModelClient([RuntimeError("sensitive provider body")]),
        ToolRegistry(),
    )
    with pytest.raises(ModelProviderError):
        asyncio.run(_invoke(provider_runtime, _request(), provider_trace))
    provider_call = provider_trace.snapshot()["model_calls"][0]
    assert provider_call["status"] == "failed"
    assert provider_call["error_type"] == "ModelProviderError"
    assert "sensitive provider body" not in str(provider_call)


def test_truncated_summary_response_is_kept_when_candidate_is_rejected() -> None:
    response = ModelResponse.from_final(
        "truncated summary text",
        finish_reason="length",
        usage={"completion_tokens": 64},
    )
    client = ScriptedStreamingModelClient([[response]])
    trace = AgentTraceCollector(capture_full_calls=True)
    runtime = AgentRuntime(client, ToolRegistry())  # type: ignore[arg-type]
    request = build_compaction_request(
        previous_summary=None,
        current_user_message=UserMessage(content="question"),
        prefix_messages=[UserMessage(content="older history")],
        current_user_prefix_index=None,
        max_input_bytes=10_000,
        max_output_tokens=64,
    )

    with pytest.raises(CompactionSummaryError, match="compaction summary was truncated"):
        asyncio.run(
            runtime._generate_compaction_summary(
                request,
                token=CancellationToken(),
                deadline=_Deadline(2),
                step=1,
                max_summary_bytes=1_000,
                trace_collector=trace,
            )
        )

    call = trace.snapshot()["model_calls"][0]
    assert call["purpose"] == "compaction"
    assert call["status"] == "completed"
    assert call["response"]["message"]["content"] == "truncated summary text"
    assert call["response"]["finish_reason"] == "length"
    assert call["response"]["usage"] == {"completion_tokens": 64}
    assert trace.snapshot()["compaction_calls"][0]["error_code"] == "summary_output_truncated"
