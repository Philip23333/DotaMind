from __future__ import annotations

import asyncio

from pydantic import BaseModel

from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.runtime_context import (
    ContextPressure,
    RuntimeContext,
    RuntimePhase,
    TimePressure,
)
from app.vnext.agent.trace import AgentTraceCollector, runtime_context_to_dict
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelRequest,
    ModelResponse,
    SystemMessage,
    ToolCall,
    UserMessage,
)
from app.vnext.tools import ToolDefinition, ToolRegistry
from tests.vnext.fakes import ScriptedModelClient


class EchoInput(BaseModel):
    value: int


class EchoOutput(BaseModel):
    value: int


def _call(call_id: str = "call-1", value: int = 1) -> ToolCall:
    return ToolCall(id=call_id, name="echo", arguments={"value": value})


def _tool_turn(*calls: ToolCall) -> ModelResponse:
    return ModelResponse(
        message=AssistantMessage(content=None, tool_calls=list(calls))
    )


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="Return the input.",
            input_model=EchoInput,
            output_model=EchoOutput,
            handler=lambda args: EchoOutput(value=args.value),
        )
    )
    return registry


def test_trace_records_the_first_runtime_context_snapshot() -> None:
    model = ScriptedModelClient([ModelResponse(message=FinalMessage(content="done"))])
    collector = AgentTraceCollector()
    runtime = AgentRuntime(
        model,
        _registry(),
        limits=AgentLimits(max_steps=20, deadline_seconds=2),
    )

    _run_with_trace(runtime, collector)

    step = collector.snapshot()["steps"][0]
    assert step["runtime_context"] == {
        "phase": "exploration",
        "remaining_turns": 19,
        "time_pressure": "healthy",
        "context_pressure": "normal",
        "tools_available": True,
    }


def test_trace_runtime_context_updates_for_each_model_invocation() -> None:
    model = ScriptedModelClient(
        [
            *(_tool_turn(_call(str(index), index)) for index in range(1, 6)),
            ModelResponse(message=FinalMessage(content="done")),
        ]
    )
    collector = AgentTraceCollector()
    runtime = AgentRuntime(
        model,
        _registry(),
        limits=AgentLimits(max_steps=6, deadline_seconds=2),
    )

    _run_with_trace(runtime, collector)

    steps = collector.snapshot()["steps"]
    assert [step["runtime_context"]["remaining_turns"] for step in steps] == [
        5,
        4,
        3,
        2,
        1,
        0,
    ]
    assert steps[-1]["runtime_context"]["phase"] == "finalization"
    assert steps[-1]["runtime_context"]["tools_available"] is False


def test_trace_runtime_context_matches_the_prompt_snapshot() -> None:
    model = ScriptedModelClient(
        [_tool_turn(_call()), ModelResponse(message=FinalMessage(content="done"))]
    )
    collector = AgentTraceCollector()
    runtime = AgentRuntime(
        model,
        _registry(),
        limits=AgentLimits(max_steps=5, deadline_seconds=2),
    )

    _run_with_trace(runtime, collector)

    prompt = next(
        message for message in model.requests[0].messages if isinstance(message, SystemMessage)
    )
    trace_context = collector.snapshot()["steps"][0]["runtime_context"]
    assert "Execution phase:\nconverging" in prompt.content
    assert "Remaining turns:\n4" in prompt.content
    assert trace_context["phase"] == "converging"
    assert trace_context["remaining_turns"] == 4


def test_trace_stores_structured_context_without_runtime_prompt_text() -> None:
    model = ScriptedModelClient([ModelResponse(message=FinalMessage(content="done"))])
    collector = AgentTraceCollector()
    runtime = AgentRuntime(
        model,
        _registry(),
        limits=AgentLimits(max_steps=20, deadline_seconds=2),
    )

    _run_with_trace(runtime, collector)

    step = collector.snapshot()["steps"][0]
    assert "runtime_prompt" not in step
    assert "Runtime state:" not in str(step["model_request"])


def _run_with_trace(runtime: AgentRuntime, collector: AgentTraceCollector) -> None:
    asyncio.run(runtime.run([UserMessage(content="hello")], trace_collector=collector))


def test_trace_context_conversion_accepts_dataclass_values() -> None:
    context = RuntimeContext(
        phase=RuntimePhase.CONVERGING,
        remaining_turns=4,
        time_pressure=TimePressure.HEALTHY,
        context_pressure=ContextPressure.NORMAL,
        tools_available=True,
    )

    assert runtime_context_to_dict(context) == {
        "phase": "converging",
        "remaining_turns": 4,
        "time_pressure": "healthy",
        "context_pressure": "normal",
        "tools_available": True,
    }


def test_trace_keeps_legacy_model_request_calls_compatible() -> None:
    collector = AgentTraceCollector()

    collector.model_request(
        ModelRequest(messages=[UserMessage(content="hello")], step=1)
    )

    assert collector.snapshot()["steps"][0]["runtime_context"] is None
