from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel, ConfigDict

from app.vnext.agent.errors import AgentCancelledError, ModelProtocolError
from app.vnext.agent.events import AgentCompleted, TextDelta
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime, CancellationToken
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelResponse,
    ModelTextDelta,
    SystemMessage,
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


def _call(call_id: str = "call-1", value: int = 1) -> ToolCall:
    return ToolCall(id=call_id, name="echo", arguments={"value": value})


def _registry(handler=None, *, parallel_safe: bool = False) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="Return the input.",
            input_model=EchoInput,
            output_model=EchoOutput,
            handler=handler or (lambda args: EchoOutput(value=args.value)),
            parallel_safe=parallel_safe,
        )
    )
    return registry


def _tool_turn(*calls: ToolCall) -> ModelResponse:
    return ModelResponse(message=AssistantMessage(content=None, tool_calls=list(calls)))


def _run(runtime: AgentRuntime, **kwargs):
    return asyncio.run(runtime.run([UserMessage(content="hello")], **kwargs))


def test_execution_final_is_discarded_and_answer_stage_is_user_visible() -> None:
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution draft"), ModelResponse.from_final("answer")]
    )
    runtime = AgentRuntime(model, ToolRegistry(), limits=AgentLimits(deadline_seconds=2))

    result = _run(runtime)

    assert result.content == "answer"
    assert len(model.requests) == 2
    assert model.requests[1].tools == []
    assert model.requests[1].messages[0].content.startswith("Execution has ended.")


def test_tool_execution_is_followed_by_tool_free_answer_request() -> None:
    model = ScriptedModelClient(
        [
            _tool_turn(_call()),
            ModelResponse.from_final("execution done"),
            ModelResponse.from_final("answer"),
        ]
    )
    runtime = AgentRuntime(model, _registry(), limits=AgentLimits(deadline_seconds=2))

    assert _run(runtime).content == "answer"
    assert len(model.requests) == 3
    assert model.requests[1].messages[-1].tool_call_id == "call-1"  # type: ignore[union-attr]
    assert model.requests[2].tools == []
    assert "Other verified tool evidence" in model.requests[2].messages[-1].content


def test_runtime_always_keeps_tools_enabled_on_last_execution_turn() -> None:
    model = ScriptedModelClient([_tool_turn(_call()), ModelResponse.from_final("answer")])
    runtime = AgentRuntime(
        model,
        _registry(),
        limits=AgentLimits(max_steps=1, deadline_seconds=2),
    )

    assert _run(runtime).content == "answer"
    assert model.requests[0].tools
    assert len(model.requests) == 2


def test_execution_text_deltas_are_traced_but_not_published() -> None:
    model = ScriptedStreamingModelClient(
        [
            [ModelTextDelta(text="internal "), ModelResponse.from_final("draft")],
            [ModelTextDelta(text="visible "), ModelResponse.from_final("answer")],
        ]
    )
    events = []
    runtime = AgentRuntime(model, ToolRegistry(), limits=AgentLimits(deadline_seconds=2))

    async def collect() -> None:
        async for event in runtime.run_stream([UserMessage(content="hello")]):
            events.append(event)

    asyncio.run(collect())

    assert [event.text for event in events if isinstance(event, TextDelta)] == ["visible "]
    assert isinstance(events[-1], AgentCompleted)


def test_answer_stage_rejects_structured_tool_calls() -> None:
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), _tool_turn(_call())]
    )
    runtime = AgentRuntime(model, _registry(), limits=AgentLimits(deadline_seconds=2))

    with pytest.raises(ModelProtocolError):
        _run(runtime)


def test_deadline_freezes_execution_and_runs_independent_answer_stage() -> None:
    async def slow() -> ModelResponse:
        await asyncio.sleep(0.2)
        return ModelResponse.from_final("late")

    model = ScriptedModelClient([slow(), ModelResponse.from_final("deadline answer")])
    collector = AgentTraceCollector()
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=0.03, answer_timeout_seconds=1),
    )

    assert _run(runtime, trace_collector=collector).content == "deadline answer"
    trace = collector.snapshot()
    assert trace["execution_outcome"] == {
        "reason": "deadline",
        "steps": 1,
        "plan_complete": False,
    }
    assert trace["answer_stage"]["tool_count"] == 0


def test_cancellation_during_execution_skips_answer_stage() -> None:
    token = CancellationToken()

    async def slow() -> ModelResponse:
        await asyncio.sleep(1)
        return ModelResponse.from_final("late")

    model = ScriptedModelClient([slow(), ModelResponse.from_final("never")])
    runtime = AgentRuntime(model, ToolRegistry(), limits=AgentLimits(deadline_seconds=2))

    async def run_and_cancel() -> None:
        task = asyncio.create_task(
            runtime.run([UserMessage(content="hello")], cancellation_token=token)
        )
        await asyncio.sleep(0.01)
        token.cancel()
        with pytest.raises(AgentCancelledError):
            await task

    asyncio.run(run_and_cancel())
    assert len(model.requests) == 1


def test_system_instruction_is_execution_only() -> None:
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=2),
        system_instruction="query discipline",
    )

    _run(runtime)

    assert model.requests[0].messages[0].content.startswith(
        "query discipline\n\nRuntime state:"
    )
    assert model.requests[1].messages[0].content.startswith("Execution has ended.")
    assert "query discipline" not in model.requests[1].messages[0].content


def test_trace_records_execution_outcome_and_answer_metrics() -> None:
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )
    collector = AgentTraceCollector()
    runtime = AgentRuntime(model, ToolRegistry(), limits=AgentLimits(deadline_seconds=2))

    _run(runtime, trace_collector=collector)

    trace = collector.snapshot()
    assert trace["execution_outcome"]["reason"] == "model_done"
    assert trace["execution_outcome"]["steps"] == 1
    assert trace["answer_stage"]["tool_count"] == 0
    assert trace["answer_stage"]["context_bytes"] > 0


def test_runtime_rejects_caller_system_message_when_system_instruction_configured() -> None:
    model = ScriptedModelClient([ModelResponse.from_final("never")])
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=2),
        system_instruction="runtime system",
    )

    with pytest.raises(ModelProtocolError):
        asyncio.run(
            runtime.run(
                [SystemMessage(content="caller system"), UserMessage(content="hello")]
            )
        )
    assert model.requests == []
