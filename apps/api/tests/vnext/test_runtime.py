from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel, ConfigDict

from app.vnext.agent.errors import AgentCancelledError, ModelProtocolError
from app.vnext.agent.events import AgentCompleted, TextDelta
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime, CancellationToken
from app.vnext.agent.task_state import (
    TaskCheckpoint,
    TaskItem,
    TaskItemStatus,
    TaskPlan,
    TaskStateCoordinator,
)
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


def test_max_steps_without_durable_state_closes_with_failure_answer() -> None:
    model = ScriptedModelClient([_tool_turn(_call()), ModelResponse.from_final("answer")])
    runtime = AgentRuntime(
        model,
        _registry(),
        limits=AgentLimits(max_steps=1, deadline_seconds=2),
    )

    result = _run(runtime)
    assert "reliable answer" in result.content
    assert model.requests[0].tools
    assert len(model.requests) == 1


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


def test_primary_answer_protocol_failure_retries_with_degraded_answer() -> None:
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), _tool_turn(_call())]
    )
    runtime = AgentRuntime(model, _registry(), limits=AgentLimits(deadline_seconds=2))

    assert _run(runtime).content == "execution"
    assert len(model.requests) == 3
    assert model.requests[1].tools == []
    assert model.requests[2].tools == []


def test_primary_timeout_retries_with_degraded_answer() -> None:
    async def slow() -> ModelResponse:
        await asyncio.sleep(0.2)
        return ModelResponse.from_final("late")

    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), slow(), ModelResponse.from_final("compact")]
    )
    collector = AgentTraceCollector()
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(
            deadline_seconds=2,
            answer_timeout_seconds=0.03,
            degraded_answer_timeout_seconds=1,
        ),
    )

    assert _run(runtime, trace_collector=collector).content == "compact"
    assert len(model.requests) == 3
    assert collector.snapshot()["answer_attempts"][0]["status"] == "timeout"
    assert collector.snapshot()["answer_attempts"][1]["status"] == "completed"
    assert collector.snapshot()["answer_fallback"] == "degraded_model"
    assert collector.snapshot()["terminal"]["status"] == "completed"


def test_primary_and_degraded_timeout_use_deterministic_fallback() -> None:
    async def slow() -> ModelResponse:
        await asyncio.sleep(0.2)
        return ModelResponse.from_final("late")

    model = ScriptedModelClient([ModelResponse.from_final("execution"), slow(), slow()])
    collector = AgentTraceCollector()
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(
            deadline_seconds=2,
            answer_timeout_seconds=0.03,
            degraded_answer_timeout_seconds=0.03,
        ),
    )

    result = _run(runtime, trace_collector=collector)

    assert "detailed final response" in result.content
    assert len(model.requests) == 3
    assert collector.snapshot()["answer_fallback"] == "deterministic"
    assert collector.snapshot()["terminal"]["status"] == "completed"


def test_partial_double_answer_failure_reports_completed_coverage() -> None:
    async def slow() -> ModelResponse:
        await asyncio.sleep(0.2)
        return ModelResponse.from_final("late")

    coordinator = TaskStateCoordinator()
    coordinator.plan = TaskPlan(
        items=(
            TaskItem("A", "Collect A", TaskItemStatus.COMPLETED),
            TaskItem("B", "Collect B", TaskItemStatus.IN_PROGRESS),
            TaskItem("C", "Collect C", TaskItemStatus.PENDING),
        ),
        current_key="B",
    )
    coordinator.store.put(
        TaskCheckpoint(
            checkpoint_id="checkpoint:A",
            key="A",
            value={"fact": "A"},
            source_tool_call_ids=(),
        )
    )
    model = ScriptedModelClient([ModelResponse.from_final("execution"), slow(), slow()])
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(
            deadline_seconds=2,
            answer_timeout_seconds=0.03,
            degraded_answer_timeout_seconds=0.03,
        ),
        task_state_coordinator=coordinator,
    )

    result = _run(runtime)

    assert "1 of 3 planned parts were completed" in result.content
    assert "won't infer or fill them in" in result.content


def test_full_double_answer_failure_reports_completed_coverage() -> None:
    async def slow() -> ModelResponse:
        await asyncio.sleep(0.2)
        return ModelResponse.from_final("late")

    coordinator = TaskStateCoordinator()
    coordinator.plan = TaskPlan(
        items=(
            TaskItem("A", "Collect A", TaskItemStatus.COMPLETED),
            TaskItem("B", "Collect B", TaskItemStatus.COMPLETED),
        ),
        current_key=None,
    )
    for key in ("A", "B"):
        coordinator.store.put(
            TaskCheckpoint(
                checkpoint_id=f"checkpoint:{key}",
                key=key,
                value={"fact": key},
                source_tool_call_ids=(),
            )
        )
    model = ScriptedModelClient([ModelResponse.from_final("execution"), slow(), slow()])
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(
            deadline_seconds=2,
            answer_timeout_seconds=0.03,
            degraded_answer_timeout_seconds=0.03,
        ),
        task_state_coordinator=coordinator,
    )

    result = _run(runtime)

    assert "2 of 2 planned parts were completed" in result.content
    assert "remaining parts were not completed" not in result.content


def test_primary_provider_failure_retries_with_degraded_answer() -> None:
    model = ScriptedModelClient(
        [
            ModelResponse.from_final("execution"),
            ValueError("provider down"),
            ModelResponse.from_final("compact"),
        ]
    )
    runtime = AgentRuntime(model, ToolRegistry(), limits=AgentLimits(deadline_seconds=2))

    assert _run(runtime).content == "compact"
    assert len(model.requests) == 3


def test_failed_primary_stream_text_is_not_published() -> None:
    model = ScriptedStreamingModelClient(
        [
            [ModelResponse.from_final("execution")],
            [
                ModelTextDelta(text="bad partial"),
                _tool_turn(_call()),
            ],
            [
                ModelTextDelta(text="good compact"),
                ModelResponse.from_final("good compact"),
            ],
        ]
    )
    events = []
    collector = AgentTraceCollector()
    runtime = AgentRuntime(model, _registry(), limits=AgentLimits(deadline_seconds=2))

    async def collect() -> None:
        async for event in runtime.run_stream(
            [UserMessage(content="hello")], trace_collector=collector
        ):
            events.append(event)

    asyncio.run(collect())

    assert [event.text for event in events if isinstance(event, TextDelta)] == [
        "good compact"
    ]
    assert collector.snapshot()["steps"][1]["streamed_text"] == ["bad partial"]


def test_cancellation_during_primary_answer_skips_degraded_retry() -> None:
    token = CancellationToken()
    primary_started = asyncio.Event()

    async def slow() -> ModelResponse:
        primary_started.set()
        await asyncio.sleep(1)
        return ModelResponse.from_final("late")

    model = ScriptedModelClient([ModelResponse.from_final("execution"), slow()])
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=2, answer_timeout_seconds=1),
    )

    async def run_and_cancel() -> None:
        task = asyncio.create_task(
            runtime.run([UserMessage(content="hello")], cancellation_token=token)
        )
        await primary_started.wait()
        token.cancel()
        with pytest.raises(AgentCancelledError):
            await task

    asyncio.run(run_and_cancel())
    assert len(model.requests) == 2


def test_deadline_without_durable_state_closes_with_failure_answer() -> None:
    async def slow() -> ModelResponse:
        await asyncio.sleep(0.2)
        return ModelResponse.from_final("late")

    model = ScriptedModelClient([slow(), ModelResponse.from_final("unexpected answer")])
    collector = AgentTraceCollector()
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=0.03, answer_timeout_seconds=1),
    )

    result = _run(runtime, trace_collector=collector)
    assert "reliable answer" in result.content
    assert len(model.requests) == 1
    trace = collector.snapshot()
    assert trace["execution_outcome"] == {
        "reason": "deadline",
        "steps": 1,
        "plan_complete": False,
    }
    assert trace["answer_resolution"] == {
        "mode": "failure",
        "execution_reason": "deadline",
        "total_items": None,
        "completed_count": 0,
        "remaining_count": 0,
        "completed_keys": [],
        "remaining_keys": [],
    }
    assert "answer_stage" not in trace
    assert trace["terminal"]["status"] == "completed"
    assert trace["terminal"]["error_code"] is None
    assert trace["terminal"]["error_message"] is None


def test_partial_task_state_still_runs_answer_stage() -> None:
    coordinator = TaskStateCoordinator()
    coordinator.plan = TaskPlan(
        items=(
            TaskItem("A", "Collect A", TaskItemStatus.COMPLETED),
            TaskItem("B", "Collect B", TaskItemStatus.IN_PROGRESS),
        ),
        current_key="B",
    )
    coordinator.store.put(
        TaskCheckpoint(
            checkpoint_id="checkpoint:A",
            key="A",
            value={"fact": "A"},
            source_tool_call_ids=(),
        )
    )
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("partial answer")]
    )
    collector = AgentTraceCollector()
    runtime = AgentRuntime(
        model,
        ToolRegistry(),
        limits=AgentLimits(deadline_seconds=2),
        task_state_coordinator=coordinator,
    )

    assert _run(runtime, trace_collector=collector).content == "partial answer"
    assert len(model.requests) == 2
    assert model.requests[1].tools == []
    trace = collector.snapshot()
    assert trace["answer_resolution"]["mode"] == "partial"
    assert "answer_stage" in trace


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


def test_parallel_group_advances_once_and_runs_following_serial_call() -> None:
    state = {"active": 0, "maximum": 0, "serial_started_with_active": None}

    async def parallel_handler(args: EchoInput) -> EchoOutput:
        state["active"] += 1
        state["maximum"] = max(state["maximum"], state["active"])
        await asyncio.sleep(0.01)
        state["active"] -= 1
        return EchoOutput(value=args.value)

    async def serial_handler(args: EchoInput) -> EchoOutput:
        state["serial_started_with_active"] = state["active"]
        return EchoOutput(value=args.value)

    registry = ToolRegistry()
    for name in ("parallel_a", "parallel_b"):
        registry.register(
            ToolDefinition(
                name=name,
                description=name,
                input_model=EchoInput,
                output_model=EchoOutput,
                handler=parallel_handler,
                parallel_safe=True,
            )
        )
    registry.register(
        ToolDefinition(
            name="serial_c",
            description="serial_c",
            input_model=EchoInput,
            output_model=EchoOutput,
            handler=serial_handler,
            parallel_safe=False,
        )
    )
    model = ScriptedModelClient(
        [
            _tool_turn(
                ToolCall(id="a", name="parallel_a", arguments={"value": 1}),
                ToolCall(id="b", name="parallel_b", arguments={"value": 2}),
                ToolCall(id="c", name="serial_c", arguments={"value": 3}),
            ),
            ModelResponse.from_final("execution"),
            ModelResponse.from_final("answer"),
        ]
    )

    assert (
        _run(AgentRuntime(model, registry, limits=AgentLimits(deadline_seconds=2))).content
        == "answer"
    )

    tool_results = [
        message for message in model.requests[1].messages if hasattr(message, "tool_call_id")
    ]
    assert [message.tool_call_id for message in tool_results] == ["a", "b", "c"]
    assert state["maximum"] == 2
    assert state["serial_started_with_active"] == 0


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
