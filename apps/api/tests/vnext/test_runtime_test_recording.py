from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from pydantic import BaseModel

from app.vnext.agent.errors import (
    AgentCancelledError,
    AgentDeadlineExceeded,
    ModelProviderError,
)
from app.vnext.agent.evidence_summary_lifecycle import (
    CompactionSummaryError,
    build_history_compaction_request,
)
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime, CancellationToken, _Deadline
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.openai_compatible import OpenAICompatibleModelClient
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
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
    response, _ = await runtime._invoke_model(
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
            application_max_output_tokens=2048,
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


def test_split_compaction_calls_use_existing_full_call_recording() -> None:
    request_id = uuid4()
    history = SessionExecutionHistory()
    history.begin_request(
        request_id,
        "current question",
        initial_messages=[
            UserMessage(content="older question"),
            FinalMessage(content="older answer"),
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
    model = ScriptedModelClient(
        [
            ModelResponse.from_final(
                "updated history",
                finish_reason="stop",
                usage={"completion_tokens": 3},
            ),
            ModelResponse.from_final(
                "turn progress",
                finish_reason="stop",
                usage={"completion_tokens": 4},
            ),
            ModelResponse.from_final("execution"),
            ModelResponse.from_final("answer"),
        ]
    )
    trace = AgentTraceCollector(capture_full_calls=True)
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(
            deadline_seconds=2,
            compaction_keep_recent_tokens=1,
            application_max_output_tokens=4096,
        ),
    )

    asyncio.run(
        runtime.run(
            history.effective_messages(),
            execution_history=history,
            request_id=request_id,
            compact_before_steps=(1,),
            trace_collector=trace,
        )
    )

    calls = trace.snapshot()["model_calls"]
    assert [call["purpose"] for call in calls] == [
        "compaction",
        "compaction",
        "execution",
        "primary_answer",
    ]
    assert [call["request"]["metadata"].get("compaction_kind") for call in calls[:2]] == [
        "history",
        "turn_prefix",
    ]
    assert [call["response"]["message"]["content"] for call in calls[:2]] == [
        "updated history",
        "turn progress",
    ]
    assert [call["response"]["usage"] for call in calls[:2]] == [
        {"completion_tokens": 3},
        {"completion_tokens": 4},
    ]
    assert [call["status"] for call in calls] == ["completed"] * 4


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
    response = asyncio.run(_invoke(runtime, _request(), BrokenRecording(capture_full_calls=True)))

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


@pytest.mark.parametrize(
    "purpose",
    ["execution", "primary_answer", "degraded_answer", "compaction"],
)
@pytest.mark.parametrize("capture_full_calls", [True, False])
def test_response_diagnostics_are_associated_with_all_call_purposes(
    purpose: str,
    capture_full_calls: bool,
) -> None:
    raw_arguments = '{"value": 1 nope}'

    def handler(request: httpx.Request) -> httpx.Response:
        chunks = [
            {
                "choices": [
                    {
                        "delta": {
                            "content": "partial answer",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-1",
                                    "function": {
                                        "name": "sample_lookup",
                                        "arguments": raw_arguments[:11],
                                    },
                                }
                            ],
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"arguments": raw_arguments[11:]},
                                }
                            ]
                        },
                        "finish_reason": "length",
                    }
                ]
            },
            {"choices": [], "usage": {"completion_tokens": 19}},
        ]
        body = "".join(
            f"data: {json.dumps(chunk, ensure_ascii=False, separators=(',', ':'))}\n\n"
            for chunk in chunks
        ) + "data: [DONE]\n\n"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=body,
            request=request,
        )

    model = OpenAICompatibleModelClient(
        api_key="offline-test-key",
        base_url="https://provider.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    executions = 0

    def execute_tool(_args: _ToolArgs) -> _ToolResult:
        nonlocal executions
        executions += 1
        return _ToolResult(value=1)

    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="sample.lookup",
            description="Lookup a sample.",
            input_model=_ToolArgs,
            output_model=_ToolResult,
            handler=execute_tool,
        )
    )
    runtime = AgentRuntime(model, tools)
    trace = AgentTraceCollector(capture_full_calls=capture_full_calls)
    request = ModelRequest(
        messages=[UserMessage(content="question")],
        tools=tools.schemas(),
        step=3,
    )

    with pytest.raises(ModelProviderError) as raised:
        asyncio.run(_invoke(runtime, request, trace, purpose=purpose))

    assert raised.value.code == "model_provider_error"
    assert executions == 0
    snapshot = trace.snapshot()
    if capture_full_calls:
        call = snapshot["model_calls"][0]
        diagnostic = call["failure_diagnostics"]
        assert call["response"] is None
        assert call["partial_text"] == "partial answer"
        assert call["status"] == "failed"
        assert call["error_type"] == "ModelProviderError"
        assert diagnostic["tool_calls"][0]["raw_arguments"] == raw_arguments
    else:
        assert "model_calls" not in snapshot
        step = snapshot["steps"][0]
        assert step["streamed_text"] == ["partial answer"]
        diagnostic = step["model_failure_diagnostics"][0]
        assert diagnostic["purpose"] == purpose
        assert "raw_arguments" not in diagnostic["tool_calls"][0]
        assert "arguments_prefix" not in diagnostic["tool_calls"][0]
        assert "arguments_suffix" not in diagnostic["tool_calls"][0]
    assert diagnostic["stage"] == "tool_arguments_decode"
    assert diagnostic["response_mode"] == "stream"
    assert diagnostic["finish_reason"] == "length"
    assert diagnostic["usage"] == {"completion_tokens": 19}
    assert diagnostic["stream_done_received"] is True
    assert diagnostic["failed_tool_call_index"] == 0
    assert diagnostic["tool_calls"][0]["provider_name"] == "sample_lookup"
    assert diagnostic["tool_calls"][0]["agent_name"] == "sample.lookup"


def test_collector_diagnostic_failure_does_not_replace_model_error() -> None:
    class BrokenDiagnosticRecording(AgentTraceCollector):
        def model_call_failure_diagnostics(self, *_args, **_kwargs) -> None:
            raise RuntimeError("sensitive collector failure")

    def handler(request: httpx.Request) -> httpx.Response:
        event = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "function": {"name": "echo", "arguments": "not-json"},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        body = f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=body,
            request=request,
        )

    runtime = AgentRuntime(
        OpenAICompatibleModelClient(
            api_key="offline-test-key",
            base_url="https://provider.test/v1",
            model="test-model",
            transport=httpx.MockTransport(handler),
        ),
        ToolRegistry(),
    )
    with pytest.raises(ModelProviderError) as raised:
        asyncio.run(
            _invoke(
                runtime,
                _request(),
                BrokenDiagnosticRecording(capture_full_calls=True),
            )
        )
    assert raised.value.code == "model_provider_error"
    assert "sensitive collector failure" not in str(raised.value)


def test_runtime_does_not_execute_tool_from_malformed_provider_arguments() -> None:
    executions = 0

    def execute_tool(_args: _ToolArgs) -> _ToolResult:
        nonlocal executions
        executions += 1
        return _ToolResult(value=1)

    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            name="sample.lookup",
            description="Lookup a sample.",
            input_model=_ToolArgs,
            output_model=_ToolResult,
            handler=execute_tool,
        )
    )
    raw_arguments = '{"value": 1 nope}'

    def handler(request: httpx.Request) -> httpx.Response:
        event = {
            "choices": [
                {
                    "delta": {
                        "content": "partial answer",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-runtime",
                                "function": {
                                    "name": "sample_lookup",
                                    "arguments": raw_arguments,
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        body = (
            f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
            + "data: [DONE]\n\n"
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=body,
            request=request,
        )

    runtime = AgentRuntime(
        OpenAICompatibleModelClient(
            api_key="offline-test-key",
            base_url="https://provider.test/v1",
            model="test-model",
            transport=httpx.MockTransport(handler),
        ),
        tools,
        limits=AgentLimits(application_max_output_tokens=4096),
    )
    trace = AgentTraceCollector(capture_full_calls=True)

    async def run():
        return [
            event
            async for event in runtime.run_stream(
                [UserMessage(content="run the tool")],
                trace_collector=trace,
            )
        ]

    events = asyncio.run(run())

    assert executions == 0
    assert not any(type(event).__name__.startswith("Tool") for event in events)
    snapshot = trace.snapshot()
    recoveries = snapshot["generation_recoveries"]
    assert len(recoveries) == 3
    assert all(item["executed_count"] == 0 for item in recoveries)
    assert [item["next_action"] for item in recoveries] == [
        "correct",
        "correct",
        "finalize",
    ]
    assert "RAW" not in json.dumps(recoveries)
    assert any(
        entry.get("failure_diagnostics", {}).get("tool_calls", [{}])[0].get("agent_name")
        == "sample.lookup"
        for entry in snapshot["model_calls"]
    )


def test_truncated_summary_response_is_kept_when_candidate_is_rejected() -> None:
    response = ModelResponse.from_final(
        "truncated summary text",
        finish_reason="length",
        usage={"completion_tokens": 64},
    )
    client = ScriptedStreamingModelClient([[response]])
    trace = AgentTraceCollector(capture_full_calls=True)
    runtime = AgentRuntime(client, ToolRegistry())  # type: ignore[arg-type]
    request = build_history_compaction_request(
        previous_summary=None,
        history_messages=[UserMessage(content="older history")],
        max_output_tokens=64,
    )

    with pytest.raises(CompactionSummaryError, match="compaction summary was truncated"):
        asyncio.run(
            runtime._generate_compaction_summary(
                request,
                kind="history",
                token=CancellationToken(),
                deadline=_Deadline(2),
                step=1,
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
