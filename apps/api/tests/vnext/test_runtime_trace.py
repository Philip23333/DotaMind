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
    ModelRequest,
    ModelResponse,
    ToolCall,
    UserMessage,
)
from app.vnext.tools import ToolDefinition, ToolRegistry
from tests.vnext.fakes import ScriptedModelClient


class EchoInput(BaseModel):
    value: int


class EchoOutput(BaseModel):
    value: int


def _call() -> ToolCall:
    return ToolCall(id="call-1", name="echo", arguments={"value": 1})


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


def _run(runtime: AgentRuntime, collector: AgentTraceCollector) -> None:
    asyncio.run(runtime.run([UserMessage(content="hello")], trace_collector=collector))


def test_trace_records_execution_context_and_answer_stage_metrics() -> None:
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )
    collector = AgentTraceCollector()
    _run(
        AgentRuntime(
            model,
            _registry(),
            limits=AgentLimits(max_steps=20, deadline_seconds=2),
        ),
        collector,
    )

    snapshot = collector.snapshot()
    assert snapshot["steps"][0]["runtime_context"] == {
        "phase": "exploration",
        "remaining_turns": 19,
        "time_pressure": "healthy",
        "context_pressure": "normal",
        "tools_available": True,
    }
    assert snapshot["execution_outcome"] == {
        "reason": "model_done",
        "steps": 1,
        "plan_complete": False,
    }
    assert snapshot["answer_stage"]["tool_count"] == 0
    assert snapshot["answer_stage"]["context_bytes"] > 0


def test_trace_context_updates_until_max_steps_without_finalization_phase() -> None:
    model = ScriptedModelClient(
        [
            *(
                ModelResponse(
                    message=AssistantMessage(
                        content=None,
                        tool_calls=[
                            ToolCall(
                                id=f"call-{index}",
                                name="echo",
                                arguments={"value": index},
                            )
                        ],
                    )
                )
                for index in range(1, 4)
            ),
            ModelResponse.from_final("answer"),
        ]
    )
    collector = AgentTraceCollector()
    _run(
        AgentRuntime(
            model,
            _registry(),
            limits=AgentLimits(max_steps=3, deadline_seconds=2),
        ),
        collector,
    )

    steps = [
        step for step in collector.snapshot()["steps"] if step["runtime_context"] is not None
    ]
    assert [step["runtime_context"]["remaining_turns"] for step in steps] == [2, 1, 0]
    assert all(step["runtime_context"]["tools_available"] for step in steps)
    assert collector.snapshot()["execution_outcome"]["reason"] == "max_steps"


def test_trace_keeps_legacy_model_request_calls_compatible() -> None:
    collector = AgentTraceCollector()

    collector.model_request(ModelRequest(messages=[UserMessage(content="hello")], step=1))

    assert collector.snapshot()["steps"][0]["runtime_context"] is None


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
