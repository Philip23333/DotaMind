from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from app.vnext.agent.errors import (
    AgentCancelledError,
    AgentDeadlineExceeded,
    MaxStepsExceeded,
    MaxToolCallsExceeded,
)
from app.vnext.agent.events import AgentCompleted, TextDelta
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime, CancellationToken
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelResponse,
    ModelTextDelta,
    ToolCall,
    UserMessage,
)
from app.vnext.tools import ToolDefinition, ToolRegistry
from tests.vnext.fakes import ScriptedModelClient, ScriptedStreamingModelClient


class EchoInput(BaseModel):
    value: int


class EchoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


def _call(call_id: str = "call-1", value: int = 1, name: str = "echo") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments={"value": value})


def _registry(
    handler=None,
    *,
    parallel_safe: bool = False,
    timeout: float | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="Return the input.",
            input_model=EchoInput,
            output_model=EchoOutput,
            handler=handler or (lambda args: EchoOutput(value=args.value)),
            parallel_safe=parallel_safe,
            timeout=timeout,
        )
    )
    return registry


def _tool_turn(*calls: ToolCall) -> ModelResponse:
    return ModelResponse(
        message=AssistantMessage(content=None, tool_calls=list(calls))
    )


def _run(runtime: AgentRuntime, model: ScriptedModelClient, **kwargs):
    return asyncio.run(runtime.run([UserMessage(content="hello")], **kwargs))


def test_direct_final_answer_and_zero_tool_call_assistant_are_final() -> None:
    for response in (
        ModelResponse(message=FinalMessage(content="direct")),
        ModelResponse(message=AssistantMessage(content="text-only")),
    ):
        model = ScriptedModelClient([response])
        runtime = AgentRuntime(model, ToolRegistry(), limits=AgentLimits(deadline_seconds=2))
        result = _run(runtime, model)
        assert result.content in {"direct", "text-only"}
        assert len(model.requests) == 1


def test_single_tool_call_result_then_final() -> None:
    model = ScriptedModelClient(
        [_tool_turn(_call()), ModelResponse(message=FinalMessage(content="done"))]
    )
    runtime = AgentRuntime(model, _registry(), limits=AgentLimits(deadline_seconds=2))
    result = _run(runtime, model)
    assert result.content == "done"
    assert model.requests[1].messages[-1].tool_call_id == "call-1"  # type: ignore[union-attr]
    assert model.requests[1].messages[-1].content == {"value": 1}  # type: ignore[union-attr]


def test_multiple_tool_calls_preserve_assistant_and_result_order_and_ids() -> None:
    model = ScriptedModelClient(
        [
            _tool_turn(_call("a", 1), _call("b", 2)),
            ModelResponse(message=FinalMessage(content="done")),
        ]
    )
    runtime = AgentRuntime(
        model,
        _registry(parallel_safe=True),
        limits=AgentLimits(deadline_seconds=2),
    )
    _run(runtime, model)
    transcript = model.requests[1].messages
    assert isinstance(transcript[-3], AssistantMessage)
    assert [call.id for call in transcript[-3].tool_calls] == ["a", "b"]
    assert [message.tool_call_id for message in transcript[-2:]] == ["a", "b"]  # type: ignore[attr-defined]


def test_multiple_reasoning_turns_are_sent_as_a_complete_transcript() -> None:
    model = ScriptedModelClient(
        [
            _tool_turn(_call("one", 1)),
            _tool_turn(_call("two", 2)),
            ModelResponse(message=FinalMessage(content="finished")),
        ]
    )
    runtime = AgentRuntime(model, _registry(), limits=AgentLimits(deadline_seconds=2))
    assert _run(runtime, model).content == "finished"
    assert len(model.requests) == 3
    assert isinstance(model.requests[2].messages[1], AssistantMessage)
    assert isinstance(model.requests[2].messages[2], object)
    assert isinstance(model.requests[2].messages[3], AssistantMessage)


def test_tool_local_errors_are_results_and_model_can_continue() -> None:
    cases = [
        ("unknown", _tool_turn(_call(name="missing")), "unknown_tool"),
        (
            "invalid",
            _tool_turn(ToolCall(id="bad", name="echo", arguments={"value": "x"})),
            "invalid_arguments",
        ),
        ("handler", _tool_turn(_call()), "tool_execution_error"),
        ("output", _tool_turn(_call()), "invalid_tool_output"),
        ("timeout", _tool_turn(_call()), "tool_timeout"),
    ]
    for label, first_response, expected_code in cases:
        if label == "handler":
            registry = _registry(handler=lambda args: (_ for _ in ()).throw(RuntimeError("boom")))
        elif label == "output":
            registry = _registry(handler=lambda args: {"wrong": args.value})
        elif label == "timeout":
            async def slow(args: EchoInput) -> EchoOutput:
                await asyncio.sleep(0.03)
                return EchoOutput(value=args.value)

            registry = _registry(handler=slow, timeout=0.001)
        else:
            registry = _registry()
        model = ScriptedModelClient(
            [first_response, ModelResponse(message=FinalMessage(content=label))]
        )
        runtime = AgentRuntime(model, registry, limits=AgentLimits(deadline_seconds=2))
        result = _run(runtime, model)
        tool_result = model.requests[1].messages[-1]
        assert result.content == label
        assert tool_result.status == "error"  # type: ignore[union-attr]
        assert tool_result.error.code == expected_code  # type: ignore[union-attr]


def test_total_tool_call_budget_is_runtime_failure() -> None:
    model = ScriptedModelClient([_tool_turn(_call("a"), _call("b"))])
    runtime = AgentRuntime(
        model,
        _registry(),
        limits=AgentLimits(max_tool_calls=1, deadline_seconds=2),
    )
    with pytest.raises(MaxToolCallsExceeded):
        _run(runtime, model)


def test_max_steps_is_runtime_failure_after_allowed_tool_turn() -> None:
    model = ScriptedModelClient([_tool_turn(_call())])
    runtime = AgentRuntime(
        model,
        _registry(),
        limits=AgentLimits(max_steps=1, deadline_seconds=2),
    )
    with pytest.raises(MaxStepsExceeded):
        _run(runtime, model)


def test_overall_deadline_is_not_a_tool_success() -> None:
    async def slow_model(request):
        await asyncio.sleep(0.03)
        return ModelResponse(message=FinalMessage(content="late"))

    model = ScriptedModelClient([slow_model(None)])
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=0.001),
    )
    with pytest.raises(AgentDeadlineExceeded):
        _run(runtime, model)


def test_cancellation_before_model_call() -> None:
    model = ScriptedModelClient([ModelResponse(message=FinalMessage(content="never"))])
    token = CancellationToken()
    token.cancel()
    runtime = AgentRuntime(model, ToolRegistry(), limits=AgentLimits(deadline_seconds=2))
    with pytest.raises(AgentCancelledError):
        _run(runtime, model, cancellation_token=token)
    assert model.requests == []


def test_cancellation_during_tool_execution_is_runtime_failure() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked(args: EchoInput) -> EchoOutput:
        started.set()
        await release.wait()
        return EchoOutput(value=args.value)

    async def exercise() -> None:
        model = ScriptedModelClient(
            [_tool_turn(_call()), ModelResponse(message=FinalMessage(content="never"))]
        )
        token = CancellationToken()
        runtime = AgentRuntime(
            model,
            _registry(handler=blocked),
            limits=AgentLimits(deadline_seconds=2),
        )
        task = asyncio.create_task(
            runtime.run([UserMessage(content="go")], cancellation_token=token)
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        token.cancel()
        with pytest.raises(AgentCancelledError):
            await task
        assert len(model.requests) == 1

    asyncio.run(exercise())


def test_runtime_event_order_and_streaming() -> None:
    model = ScriptedModelClient(
        [_tool_turn(_call()), ModelResponse(message=FinalMessage(content="done"))]
    )
    runtime = AgentRuntime(model, _registry(), limits=AgentLimits(deadline_seconds=2))

    async def collect():
        return [
            event
            async for event in runtime.run_stream([UserMessage(content="go")])
        ]

    events = asyncio.run(collect())
    assert [event.kind for event in events] == [
        "agent_started",
        "model_requested",
        "model_responded",
        "tool_started",
        "tool_completed",
        "model_requested",
        "model_responded",
        "agent_completed",
    ]
    assert isinstance(events[-1], AgentCompleted)
    assert events[-1].final.content == "done"  # type: ignore[union-attr]


def test_runtime_streams_text_deltas_before_model_response_and_final() -> None:
    model = ScriptedStreamingModelClient(
        [
            [
                ModelTextDelta(text="Hel"),
                ModelTextDelta(text="lo"),
                ModelResponse.from_final("Hello"),
            ]
        ]
    )
    runtime = AgentRuntime(model, ToolRegistry(), limits=AgentLimits(deadline_seconds=2))

    async def collect():
        return [
            event
            async for event in runtime.run_stream([UserMessage(content="go")])
        ]

    events = asyncio.run(collect())
    assert [event.kind for event in events] == [
        "agent_started",
        "model_requested",
        "text_delta",
        "text_delta",
        "model_responded",
        "agent_completed",
    ]
    assert [event.text for event in events if isinstance(event, TextDelta)] == ["Hel", "lo"]
    assert isinstance(events[-1], AgentCompleted)
    assert events[-1].final.content == "Hello"


def test_runtime_streams_deltas_then_continues_tool_loop_without_repeating_text() -> None:
    model = ScriptedStreamingModelClient(
        [
            [
                ModelTextDelta(text="checking "),
                ModelResponse(
                    message=AssistantMessage(
                        content="checking ",
                        tool_calls=[_call()],
                    )
                ),
            ],
            [ModelTextDelta(text="done"), ModelResponse.from_final("done")],
        ]
    )
    runtime = AgentRuntime(model, _registry(), limits=AgentLimits(deadline_seconds=2))

    async def collect():
        return [
            event
            async for event in runtime.run_stream([UserMessage(content="go")])
        ]

    events = asyncio.run(collect())
    assert [event.kind for event in events] == [
        "agent_started",
        "model_requested",
        "text_delta",
        "model_responded",
        "tool_started",
        "tool_completed",
        "model_requested",
        "text_delta",
        "model_responded",
        "agent_completed",
    ]
    assert [event.text for event in events if isinstance(event, TextDelta)] == [
        "checking ",
        "done",
    ]
    assert model.requests[1].messages[-1].content == {"value": 1}  # type: ignore[union-attr]
    assert events[-1].final.content == "done"  # type: ignore[union-attr]


def test_vnext_runtime_has_no_legacy_or_langgraph_import_dependency() -> None:
    root = Path(__file__).parents[2] / "app" / "vnext"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    forbidden = (
        "app.agentic",
        "langgraph",
        "ExecutionPlan",
        "EvidenceGraph",
        "Controller",
        "Scenario Router",
    )
    assert not any(term in source for term in forbidden)
