from __future__ import annotations

import asyncio
import json
from typing import Any

from pydantic import BaseModel

from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.materialization_budget import MaterializationBudget
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.artifacts import ArtifactObservationTranscriptRewriter, ArtifactReadResult
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.tools import ToolContextEffect, ToolDefinition, ToolRegistry
from app.vnext.tools.artifacts.retrieval import ArtifactReadInput
from app.vnext.tools.task import register_task_checkpoint_tool, register_task_plan_tool
from tests.vnext.fakes import ScriptedModelClient, ScriptedTranscriptModelClient


def _size(value: Any) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    )


def test_materialization_budget_admits_at_limit_defers_over_limit_and_releases() -> None:
    budget = MaterializationBudget(100)

    first = budget.admit("a", raw_bytes=40)
    second = budget.admit("b", raw_bytes=60)
    deferred = budget.admit("c", raw_bytes=1)

    assert first.admitted is True
    assert first.active_before_bytes == 0
    assert first.active_after_bytes == 40
    assert second.admitted is True
    assert second.active_after_bytes == 100
    assert deferred.admitted is False
    assert deferred.active_before_bytes == 100
    assert deferred.active_after_bytes == 100
    assert budget.active_count == 2
    assert budget.release("a") == 40
    assert budget.release("missing") == 0
    assert budget.active_bytes == 60
    assert budget.admit("c", raw_bytes=40).admitted is True


class _ReadState:
    def __init__(self) -> None:
        self.active = 0
        self.maximum = 0
        self.task_keys: list[str | None] = []


def _read_call(call_id: str, task_key: str, offset: int) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="artifact.read",
        arguments={
            "ref": "artifact:test",
            "mode": "read",
            "path": "rows",
            "offset": offset,
            "limit": 1,
            "task_key": task_key,
        },
    )


def _plan_call() -> ToolCall:
    return ToolCall(
        id="plan",
        name="task.plan",
        arguments={
            "items": [
                {"key": "A", "objective": "retrieve A"},
                {"key": "B", "objective": "retrieve B"},
                {"key": "C", "objective": "retrieve C"},
            ]
        },
    )


def _checkpoint_call(call_id: str, key: str, source: str) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="task.checkpoint",
        arguments={
            "key": key,
            "value": {"partition": key},
            "source_tool_call_ids": [source],
        },
    )


def _tool_result(request: ModelRequest, tool_call_id: str) -> ToolResultMessage:
    return next(
        message
        for message in request.messages
        if isinstance(message, ToolResultMessage) and message.tool_call_id == tool_call_id
    )


def _read_registry(coordinator: TaskStateCoordinator, state: _ReadState) -> ToolRegistry:
    registry = ToolRegistry()

    async def read(args: ArtifactReadInput) -> ArtifactReadResult:
        state.active += 1
        state.maximum = max(state.maximum, state.active)
        state.task_keys.append(args.task_key)
        await asyncio.sleep(0.01)
        state.active -= 1
        return ArtifactReadResult(
            ref=args.ref,
            path=args.path,
            value=[{"id": 0, "payload": "x" * 400}],
            offset=args.offset or 0,
            limit=args.limit,
            total=3,
            truncated=False,
        )

    registry.register(
        ToolDefinition(
            name="artifact.read",
            description="read",
            input_model=ArtifactReadInput,
            output_model=ArtifactReadResult,
            handler=read,
            parallel_safe=True,
            externalize_result=False,
            context_effect=ToolContextEffect.MATERIALIZING,
        )
    )
    register_task_plan_tool(registry, coordinator)
    register_task_checkpoint_tool(registry, coordinator)
    return registry


def test_runtime_admits_by_plan_priority_defers_then_retries_after_release() -> None:
    coordinator = TaskStateCoordinator()
    state = _ReadState()
    probe = ToolResultMessage(
        tool_call_id="read-x",
        content=ArtifactReadResult(
            ref="artifact:test",
            path="rows",
            value=[{"id": 0, "payload": "x" * 400}],
            offset=0,
            limit=1,
            total=3,
            truncated=False,
        ).model_dump(mode="json"),
    )
    limits = AgentLimits(
        deadline_seconds=2,
        answer_timeout_seconds=2,
        max_materialized_context_bytes=2 * _size(probe.model_dump(mode="json")) + 2,
    )

    def first(_: ModelRequest) -> ModelResponse:
        return ModelResponse(message=AssistantMessage(tool_calls=[_plan_call()]))

    def second(_: ModelRequest) -> ModelResponse:
        return ModelResponse(
            message=AssistantMessage(
                tool_calls=[
                    _read_call("read-c", "C", 2),
                    _read_call("read-a", "A", 0),
                    _read_call("read-b", "B", 1),
                ]
            )
        )

    def third(request: ModelRequest) -> ModelResponse:
        read_a = _tool_result(request, "read-a").content
        read_b = _tool_result(request, "read-b").content
        read_c = _tool_result(request, "read-c").content
        assert read_a["value"]  # type: ignore[index]
        assert read_b["value"]  # type: ignore[index]
        assert read_c == {
            "_context_materialization": {
                "state": "deferred",
                "reason": "budget_exceeded",
                "retryable": True,
                "raw_bytes": read_c["_context_materialization"]["raw_bytes"],  # type: ignore[index]
            }
        }
        return ModelResponse(
            message=AssistantMessage(
                tool_calls=[_checkpoint_call("checkpoint-a", "A", "read-a")]
            )
        )

    def fourth(request: ModelRequest) -> ModelResponse:
        read_a = _tool_result(request, "read-a").content
        read_b = _tool_result(request, "read-b").content
        read_c = _tool_result(request, "read-c").content
        assert read_a["_artifact_observation"]["reason"] == "checkpointed"  # type: ignore[index]
        assert read_b["value"]  # type: ignore[index]
        assert read_c["_context_materialization"]["state"] == "deferred"  # type: ignore[index]
        return ModelResponse(
            message=AssistantMessage(
                tool_calls=[_checkpoint_call("checkpoint-b", "B", "read-b")]
            )
        )

    def fifth(request: ModelRequest) -> ModelResponse:
        read_c = _tool_result(request, "read-c").content
        assert read_c["_context_materialization"]["state"] == "deferred"  # type: ignore[index]
        return ModelResponse(
            message=AssistantMessage(tool_calls=[_read_call("retry-c", "C", 2)])
        )

    def sixth(request: ModelRequest) -> ModelResponse:
        assert _tool_result(request, "retry-c").content["value"]  # type: ignore[index]
        return ModelResponse(
            message=AssistantMessage(
                tool_calls=[_checkpoint_call("checkpoint-c", "C", "retry-c")]
            )
        )

    model = ScriptedTranscriptModelClient(
        [
            first,
            second,
            third,
            fourth,
            fifth,
            sixth,
            lambda _: ModelResponse(message=FinalMessage(content="done")),
        ]
    )
    trace = AgentTraceCollector()
    events: list[Any] = []

    async def collect(event: Any) -> None:
        events.append(event)

    runtime = AgentRuntime(
        model,
        _read_registry(coordinator, state),
        limits=limits,
        transcript_rewriter=ArtifactObservationTranscriptRewriter(
            closed_partition_lookup=coordinator.closed_partition_for_tool_call
        ),
        task_state_coordinator=coordinator,
    )
    result = asyncio.run(
        runtime.run(
            [UserMessage(content="batch")],
            event_sink=collect,
            trace_collector=trace,
        )
    )

    assert result.content == "done"
    assert state.maximum == 3
    assert set(state.task_keys[:3]) == {"A", "B", "C"}
    assert [
        event.tool_call_id
        for event in events
        if event.__class__.__name__ == "ToolCompleted"
        and event.tool_call_id in {"read-c", "read-a", "read-b"}
    ][:3] == [
        "read-c",
        "read-a",
        "read-b",
    ]
    assert coordinator.plan_snapshot().current_key is None  # type: ignore[union-attr]
    snapshot = trace.snapshot()
    active = snapshot["steps"][1]["active_evidence_lease"]
    assert active["task_key"] is None
    assert {item["task_key"] for item in active["partitions"]} == {"A", "B"}
    steps = {item["step"]: item for item in snapshot["steps"]}
    admissions = steps[2]["materialization_budget"]["admissions"]
    assert len(admissions) == 3
    admission_by_id = {item["tool_call_id"]: item for item in admissions}
    assert admission_by_id["read-a"]["admitted"] is True
    assert admission_by_id["read-b"]["admitted"] is True
    assert admission_by_id["read-c"]["admitted"] is False
    assert admission_by_id["read-c"]["raw_bytes"] > 0
    assert admission_by_id["read-c"]["active_after_bytes"] == admission_by_id["read-c"][
        "active_before_bytes"
    ]
    release_a = steps[3]["materialization_budget"]["releases"]
    assert release_a == [
        {
            "tool_call_id": "read-a",
            "reason": "checkpointed",
            "released_bytes": admission_by_id["read-a"]["raw_bytes"],
            "active_after_bytes": admission_by_id["read-b"]["raw_bytes"],
        }
    ]
    release_b = steps[4]["materialization_budget"]["releases"]
    assert release_b[0]["tool_call_id"] == "read-b"
    assert release_b[0]["reason"] == "checkpointed"
    assert release_b[0]["released_bytes"] == admission_by_id["read-b"]["raw_bytes"]
    retry_admission = steps[5]["materialization_budget"]["admissions"]
    assert retry_admission[0]["tool_call_id"] == "retry-c"
    assert retry_admission[0]["admitted"] is True
    assert steps[6]["materialization_budget"]["releases"] == [
        {
            "tool_call_id": "retry-c",
            "reason": "checkpointed",
            "released_bytes": retry_admission[0]["raw_bytes"],
            "active_after_bytes": 0,
        }
    ]
    assert snapshot["answer_stage"]["active_raw_count"] == 0


def test_materialization_budget_applies_without_a_task_plan() -> None:
    state = _ReadState()
    probe = ToolResultMessage(tool_call_id="read-a", content={"value": "x" * 400})
    limits = AgentLimits(
        deadline_seconds=2,
        answer_timeout_seconds=2,
        max_materialized_context_bytes=_size(probe.model_dump(mode="json")),
    )
    registry = ToolRegistry()

    async def read(_: BaseModel) -> dict[str, str]:
        state.active += 1
        state.maximum = max(state.maximum, state.active)
        await asyncio.sleep(0.01)
        state.active -= 1
        return {"value": "x" * 400}

    class ReadInput(BaseModel):
        value: int

    class ReadOutput(BaseModel):
        value: str

    registry.register(
        ToolDefinition(
            name="materialize",
            description="materialize",
            input_model=ReadInput,
            output_model=ReadOutput,
            handler=read,
            parallel_safe=True,
            externalize_result=False,
            context_effect=ToolContextEffect.MATERIALIZING,
        )
    )
    model = ScriptedModelClient(
        [
            ModelResponse(
                message=AssistantMessage(
                    tool_calls=[
                        ToolCall(id="read-a", name="materialize", arguments={"value": 1}),
                        ToolCall(id="read-b", name="materialize", arguments={"value": 2}),
                    ]
                )
            ),
            ModelResponse.from_final("execution"),
            ModelResponse.from_final("answer"),
        ]
    )
    runtime = AgentRuntime(model, registry, limits=limits)
    asyncio.run(runtime.run([UserMessage(content="read")]))

    assert state.maximum == 2
    assert model.requests[1].messages[-2].content == {"value": "x" * 400}  # type: ignore[union-attr]
    assert model.requests[1].messages[-1].content["_context_materialization"]["state"] == "deferred"  # type: ignore[index]


def test_partition_closed_releases_all_admitted_materialization_bytes() -> None:
    coordinator = TaskStateCoordinator()
    state = _ReadState()
    probe = ToolResultMessage(
        tool_call_id="read-x",
        content=ArtifactReadResult(
            ref="artifact:test",
            path="rows",
            value=[{"id": 0, "payload": "x" * 400}],
            offset=0,
            limit=1,
            total=3,
            truncated=False,
        ).model_dump(mode="json"),
    )
    limits = AgentLimits(
        deadline_seconds=2,
        answer_timeout_seconds=2,
        max_materialized_context_bytes=2 * _size(probe.model_dump(mode="json")) + 2,
    )

    def plan(_: ModelRequest) -> ModelResponse:
        return ModelResponse(message=AssistantMessage(tool_calls=[_plan_call()]))

    def reads(_: ModelRequest) -> ModelResponse:
        return ModelResponse(
            message=AssistantMessage(
                tool_calls=[
                    _read_call("raw-1", "A", 0),
                    _read_call("raw-2", "A", 1),
                ]
            )
        )

    def checkpoint(request: ModelRequest) -> ModelResponse:
        assert _tool_result(request, "raw-1").content["value"]  # type: ignore[index]
        assert _tool_result(request, "raw-2").content["value"]  # type: ignore[index]
        return ModelResponse(
            message=AssistantMessage(
                tool_calls=[_checkpoint_call("checkpoint-a", "A", "raw-1")]
            )
        )

    model = ScriptedTranscriptModelClient(
        [plan, reads, checkpoint, lambda _: ModelResponse.from_final("done")]
    )
    trace = AgentTraceCollector()
    runtime = AgentRuntime(
        model,
        _read_registry(coordinator, state),
        limits=limits,
        transcript_rewriter=ArtifactObservationTranscriptRewriter(
            closed_partition_lookup=coordinator.closed_partition_for_tool_call
        ),
        task_state_coordinator=coordinator,
    )
    asyncio.run(
        runtime.run([UserMessage(content="partition")], trace_collector=trace)
    )

    snapshot = trace.snapshot()
    releases = snapshot["steps"][2]["materialization_budget"]["releases"]
    assert [item["tool_call_id"] for item in releases] == ["raw-1", "raw-2"]
    assert [item["reason"] for item in releases] == [
        "checkpointed",
        "partition_closed",
    ]
    assert releases[0]["released_bytes"] > 0
    assert releases[1]["released_bytes"] > 0
    assert releases[-1]["active_after_bytes"] == 0
