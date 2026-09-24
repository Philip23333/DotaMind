from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.vnext.agent.errors import ModelProtocolError
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.agent.trace import AgentTraceCollector
from app.vnext.artifacts import ArtifactObservationTranscriptRewriter, ArtifactReadResult
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelRequest,
    ModelResponse,
    SystemMessage,
    ToolCall,
    UserMessage,
)
from app.vnext.product.session_history import SessionExecutionHistory
from app.vnext.tools.definition import ToolContextEffect, ToolDefinition
from app.vnext.tools.registry import ToolRegistry
from app.vnext.tools.task import register_task_checkpoint_tool, register_task_plan_tool
from tests.vnext.fakes import ScriptedModelClient, ScriptedTranscriptModelClient


class _LookupInput(BaseModel):
    query: str


class _LookupOutput(BaseModel):
    externalized: bool
    artifact_ref: str
    value: dict[str, str]


class _ReadInput(BaseModel):
    ref: str
    mode: str
    path: str
    task_key: str | None = None


def _call(number: int) -> ToolCall:
    return ToolCall(
        id=f"lookup-{number}",
        name="lookup",
        arguments={"query": f"event-{number}"},
    )


def _read_call(call_id: str, path: str, *, task_key: str = "first") -> ToolCall:
    return ToolCall(
        id=call_id,
        name="artifact.read",
        arguments={
            "ref": "artifact:test",
            "mode": "read",
            "path": path,
            "task_key": task_key,
        },
    )


def _plan_call() -> ToolCall:
    return ToolCall(
        id="plan-call",
        name="task.plan",
        arguments={
            "items": [
                {"key": "first", "objective": "Collect first evidence"},
                {"key": "second", "objective": "Collect second evidence"},
            ]
        },
    )


def _checkpoint_call(call_id: str, key: str, source: str) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="task.checkpoint",
        arguments={
            "key": key,
            "value": {"status": f"{key} complete"},
            "source_tool_call_ids": [source],
        },
    )


def _compaction_workflow_registry(coordinator: TaskStateCoordinator) -> ToolRegistry:
    registry = ToolRegistry()

    async def read(args: _ReadInput) -> ArtifactReadResult:
        if args.path == "rows":
            value: Any = [{"fact": f"row-{index}-" + "x" * 220} for index in range(8)]
            return ArtifactReadResult(
                ref=args.ref,
                path=args.path,
                value=value,
                offset=0,
                limit=8,
                total=len(value),
            )
        return ArtifactReadResult(ref=args.ref, path=args.path, value="summary detail")

    registry.register(
        ToolDefinition(
            name="artifact.read",
            description="Read one deterministic artifact observation.",
            input_model=_ReadInput,
            output_model=ArtifactReadResult,
            handler=read,
            externalize_result=False,
            context_effect=ToolContextEffect.MATERIALIZING,
        )
    )
    register_task_plan_tool(registry, coordinator)
    register_task_checkpoint_tool(registry, coordinator)
    return registry


def _lookup_result(number: int) -> _LookupOutput:
    return _LookupOutput(
        externalized=True,
        artifact_ref="artifact:tool:" + (str(number) * 32),
        value={"body": f"event {number} raw body"},
    )


def _registry() -> ToolRegistry:
    registry = ToolRegistry()

    async def lookup(args: _LookupInput) -> _LookupOutput:
        number = int(args.query.split("-")[-1])
        return _lookup_result(number)

    registry.register(
        ToolDefinition(
            name="lookup",
            description="Return one materialized lookup result.",
            input_model=_LookupInput,
            output_model=_LookupOutput,
            handler=lookup,
            externalize_result=False,
            context_effect=ToolContextEffect.MATERIALIZING,
        )
    )
    return registry


def _history() -> tuple[SessionExecutionHistory, object]:
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
    return history, request_id


def _runtime(
    model: object,
    *,
    recent_tokens: int,
    system_instruction: str | None = None,
) -> AgentRuntime:
    return AgentRuntime(
        model,  # type: ignore[arg-type]
        _registry(),
        limits=AgentLimits(
            deadline_seconds=2,
            compaction_keep_recent_tokens=recent_tokens,
            compaction_max_input_bytes=100_000,
            compaction_reserve_tokens=160,
            context_estimate_bytes_per_token=1,
        ),
        system_instruction=system_instruction,
    )


def _message_bytes(message: object) -> int:
    return len(
        json.dumps(
            message.model_dump(mode="json"),  # type: ignore[union-attr]
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _tool_group_bytes(number: int) -> int:
    assistant = AssistantMessage(tool_calls=[_call(number)])
    result = _lookup_result(number)
    from app.vnext.llm.protocol import ToolResultMessage

    tool_result = ToolResultMessage(
        tool_call_id=f"lookup-{number}",
        content=result.model_dump(mode="json"),
    )
    return _message_bytes(assistant) + _message_bytes(tool_result)


def _session_payload(request: ModelRequest) -> dict[str, object]:
    marker = "Session context data:\n"
    for message in request.messages:
        if isinstance(message, SystemMessage) and marker in message.content:
            payload, _ = json.JSONDecoder().raw_decode(message.content.split(marker, 1)[1])
            return payload
    raise AssertionError("session projection missing")


def _run(
    runtime: AgentRuntime,
    history: SessionExecutionHistory,
    request_id: object,
    *,
    compact_before_steps: tuple[int, ...],
    trace: AgentTraceCollector,
) -> FinalMessage:
    return asyncio.run(
        runtime.run(
            history.effective_messages(),
            execution_history=history,
            request_id=request_id,
            compact_before_steps=compact_before_steps,
            trace_collector=trace,
        )
    )


@pytest.mark.parametrize(
    ("system_instruction", "request_start_before", "request_start_after"),
    [(None, 2, 1), ("base instruction", 3, 2)],
)
def test_compaction_loop_rebuilds_messages_scope_and_budget_before_next_model_call(
    system_instruction: str | None,
    request_start_before: int,
    request_start_after: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history, request_id = _history()
    model = ScriptedModelClient(
        [
            ModelResponse.from_assistant(AssistantMessage(tool_calls=[_call(1)])),
            ModelResponse.from_assistant(AssistantMessage(tool_calls=[_call(2)])),
            ModelResponse.from_final("summary one", finish_reason="stop", usage={"n": 1}),
            ModelResponse.from_final("turn prefix one", finish_reason="stop", usage={"n": 2}),
            ModelResponse.from_final("execution final"),
            ModelResponse.from_final("answer final"),
        ]
    )
    trace = AgentTraceCollector()
    runtime = _runtime(
        model,
        recent_tokens=_tool_group_bytes(2),
        system_instruction=system_instruction,
    )
    rebuild_count = 0
    original_rebuild = runtime._rebuild_after_compaction

    def count_rebuild(**kwargs: Any):
        nonlocal rebuild_count
        rebuild_count += 1
        return original_rebuild(**kwargs)

    monkeypatch.setattr(runtime, "_rebuild_after_compaction", count_rebuild)

    result = _run(
        runtime,
        history,
        request_id,
        compact_before_steps=(3,),
        trace=trace,
    )

    assert result.content == "answer final"
    assert len(model.requests) == 6
    assert model.requests[2].tools == []
    assert model.requests[3].tools == []
    assert model.requests[2].metadata["compaction_kind"] == "history"
    assert model.requests[3].metadata["compaction_kind"] == "turn_prefix"
    assert model.requests[4].tools
    assert "event 1 raw body" not in json.dumps(
        [message.model_dump(mode="json") for message in model.requests[4].messages]
    )
    assert "event 2 raw body" in json.dumps(
        [message.model_dump(mode="json") for message in model.requests[4].messages]
    )
    assert "summary one" in _session_payload(model.requests[4])["summary"]
    assert "turn prefix one" in _session_payload(model.requests[4])["summary"]
    assert (
        sum(
            message == UserMessage(content="current question")
            for message in model.requests[4].messages
        )
        == 1
    )
    assert (
        history.effective_messages()
        == [
            UserMessage(content="current question"),
            model.requests[1].messages[-1],
        ]
        or history.effective_messages()[-1].role == "final"
    )
    assert len(trace.snapshot()["compaction_calls"]) == 2
    assert len(trace.snapshot()["compaction_commits"]) == 1
    assert rebuild_count == 1
    commit = trace.snapshot()["compaction_commits"][0]
    assert commit["step"] == 3
    assert commit["request_start_before"] == request_start_before
    assert commit["request_start_after"] == request_start_after
    assert commit["materialized_bytes_after"] < commit["materialized_bytes_before"]


def test_compaction_loop_supports_two_explicit_compactions_without_replaying_tools() -> None:
    history, request_id = _history()
    model = ScriptedModelClient(
        [
            ModelResponse.from_assistant(AssistantMessage(tool_calls=[_call(1)])),
            ModelResponse.from_assistant(AssistantMessage(tool_calls=[_call(2)])),
            ModelResponse.from_final("summary one", finish_reason="stop", usage={"n": 1}),
            ModelResponse.from_final("turn prefix one", finish_reason="stop", usage={"n": 3}),
            ModelResponse.from_assistant(AssistantMessage(tool_calls=[_call(3)])),
            ModelResponse.from_assistant(AssistantMessage(tool_calls=[_call(4)])),
            ModelResponse.from_final("summary two", finish_reason="stop", usage={"n": 2}),
            ModelResponse.from_final("execution final"),
            ModelResponse.from_final("answer final"),
        ]
    )
    trace = AgentTraceCollector()
    runtime = _runtime(model, recent_tokens=_tool_group_bytes(2))

    _run(
        runtime,
        history,
        request_id,
        compact_before_steps=(3, 5),
        trace=trace,
    )

    assert [call.id for call in [_call(1), _call(2), _call(3), _call(4)]] == [
        "lookup-1",
        "lookup-2",
        "lookup-3",
        "lookup-4",
    ]
    assert [request.tools != [] for request in model.requests] == [
        True,
        True,
        False,
        False,
        True,
        True,
        False,
        True,
        False,
    ]
    assert "summary one" in _session_payload(model.requests[4])["summary"]
    assert "turn prefix one" in _session_payload(model.requests[4])["summary"]
    assert "summary two" in _session_payload(model.requests[7])["summary"]
    assert len(trace.snapshot()["compaction_calls"]) == 3
    assert len(trace.snapshot()["compaction_commits"]) == 2
    assert [item["step"] for item in trace.snapshot()["compaction_commits"]] == [3, 5]


def test_empty_compaction_trigger_is_a_single_noop_and_normal_execution_continues() -> None:
    history, request_id = _history()
    model = ScriptedModelClient(
        [ModelResponse.from_final("execution"), ModelResponse.from_final("answer")]
    )
    trace = AgentTraceCollector()

    _run(
        _runtime(model, recent_tokens=1_000_000),
        history,
        request_id,
        compact_before_steps=(1,),
        trace=trace,
    )

    assert len(model.requests) == 2
    assert "compaction_calls" not in trace.snapshot()
    assert "compaction_commits" not in trace.snapshot()


def test_compaction_entry_rejects_wrong_request_before_reset_or_execution() -> None:
    history, request_id = _history()
    coordinator = TaskStateCoordinator()
    coordinator.create_plan(
        [
            {"key": "first", "objective": "First"},
            {"key": "second", "objective": "Second"},
        ]
    )
    before_records = history.records
    before_messages = history.effective_messages()
    before_revision = history.revision
    before_plan = coordinator.plan_snapshot()
    executions = 0

    async def lookup(_: _LookupInput) -> _LookupOutput:
        nonlocal executions
        executions += 1
        return _lookup_result(1)

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="lookup",
            description="A tool that must not execute.",
            input_model=_LookupInput,
            output_model=_LookupOutput,
            handler=lookup,
        )
    )
    model = ScriptedModelClient(
        [ModelResponse.from_assistant(AssistantMessage(tool_calls=[_call(1)]))]
    )
    runtime = AgentRuntime(
        model,
        registry,
        limits=AgentLimits(deadline_seconds=2),
        task_state_coordinator=coordinator,
    )

    with pytest.raises(ModelProtocolError, match="does not match the active request"):
        asyncio.run(
            runtime.run(
                history.effective_messages(),
                execution_history=history,
                request_id=uuid4(),
                compact_before_steps=(2,),
            )
        )

    assert model.requests == []
    assert executions == 0
    assert history.records == before_records
    assert history.effective_messages() == before_messages
    assert history.revision == before_revision
    assert coordinator.plan_snapshot() == before_plan


def test_compaction_releases_repeated_reads_and_cleans_removed_task_leases() -> None:
    history = SessionExecutionHistory()
    request_id = uuid4()
    history.begin_request(
        request_id,
        "current question",
        initial_messages=[UserMessage(content="current question")],
    )
    coordinator = TaskStateCoordinator()

    def plan(request: ModelRequest) -> ModelResponse:
        assert request.step == 1
        return ModelResponse.from_assistant(AssistantMessage(tool_calls=[_plan_call()]))

    def old_read(request: ModelRequest) -> ModelResponse:
        assert request.step == 2
        return ModelResponse.from_assistant(
            AssistantMessage(tool_calls=[_read_call("read-old", "rows")])
        )

    def current_read(request: ModelRequest) -> ModelResponse:
        assert request.step == 3
        return ModelResponse.from_assistant(
            AssistantMessage(tool_calls=[_read_call("read-current", "rows")])
        )

    def first_summary(request: ModelRequest) -> ModelResponse:
        assert request.tools == []
        assert request.metadata["purpose"] == "context_compaction"
        return ModelResponse.from_final("summary after first range", finish_reason="stop")

    def duplicate_read(request: ModelRequest) -> ModelResponse:
        assert request.step == 4
        return ModelResponse.from_assistant(
            AssistantMessage(tool_calls=[_read_call("read-duplicate", "rows")])
        )

    def new_read(request: ModelRequest) -> ModelResponse:
        assert request.step == 5
        return ModelResponse.from_assistant(
            AssistantMessage(tool_calls=[_read_call("read-new", "summary")])
        )

    def second_summary(request: ModelRequest) -> ModelResponse:
        assert request.tools == []
        assert request.metadata["purpose"] == "context_compaction"
        return ModelResponse.from_final("summary after repeated read", finish_reason="stop")

    def checkpoint_first(request: ModelRequest) -> ModelResponse:
        assert request.step == 6
        task_context = next(
            message.content
            for message in request.messages
            if isinstance(message, SystemMessage) and "CURRENT:" in message.content
        )
        assert "CURRENT: first" in task_context
        assert '"tool_call_id":"read-new"' in task_context
        assert '"tool_call_id":"read-old"' not in task_context
        assert '"tool_call_id":"read-current"' not in task_context
        assert '"tool_call_id":"read-duplicate"' not in task_context
        return ModelResponse.from_assistant(
            AssistantMessage(tool_calls=[_checkpoint_call("checkpoint-first", "first", "read-new")])
        )

    def read_second(request: ModelRequest) -> ModelResponse:
        assert request.step == 7
        assert coordinator.plan_snapshot().current_key == "second"  # type: ignore[union-attr]
        return ModelResponse.from_assistant(
            AssistantMessage(tool_calls=[_read_call("read-second", "summary", task_key="second")])
        )

    def checkpoint_second(request: ModelRequest) -> ModelResponse:
        assert request.step == 8
        return ModelResponse.from_assistant(
            AssistantMessage(
                tool_calls=[_checkpoint_call("checkpoint-second", "second", "read-second")]
            )
        )

    def answer(request: ModelRequest) -> ModelResponse:
        assert request.tools == []
        assert request.step == 9
        assert coordinator.plan_snapshot().current_key is None  # type: ignore[union-attr]
        return ModelResponse.from_final("answer")

    model = ScriptedTranscriptModelClient(
        [
            plan,
            old_read,
            current_read,
            first_summary,
            duplicate_read,
            new_read,
            second_summary,
            checkpoint_first,
            read_second,
            checkpoint_second,
            answer,
        ]
    )
    trace = AgentTraceCollector()
    runtime = AgentRuntime(
        model,
        _compaction_workflow_registry(coordinator),
        limits=AgentLimits(
            max_steps=9,
            deadline_seconds=5,
            answer_timeout_seconds=5,
            compaction_keep_recent_tokens=1,
            compaction_max_input_bytes=100_000,
            compaction_reserve_tokens=160,
            max_materialized_context_bytes=100_000,
        ),
        transcript_rewriter=ArtifactObservationTranscriptRewriter(),
        task_state_coordinator=coordinator,
    )

    result = asyncio.run(
        runtime.run(
            history.effective_messages(),
            execution_history=history,
            request_id=request_id,
            compact_before_steps=(4, 6),
            trace_collector=trace,
        )
    )

    assert result.content == "answer"
    assert coordinator.plan_snapshot() is not None
    assert coordinator.plan_snapshot().current_key is None  # type: ignore[union-attr]
    leases = coordinator.active_evidence_leases_snapshot()
    assert leases == []
    assert all(
        item.status.value == "completed"
        for item in coordinator.plan_snapshot().items  # type: ignore[union-attr]
    )
    snapshot = trace.snapshot()
    assert [commit["step"] for commit in snapshot["compaction_commits"]] == [4, 6]
    assert (
        snapshot["compaction_commits"][1]["materialized_bytes_before"]
        > snapshot["compaction_commits"][1]["materialized_bytes_after"]
    )
    assert any(
        release["tool_call_id"] == "read-current"
        and release["reason"] == "duplicate"
        and release["released_bytes"] > 0
        for step in snapshot["steps"]
        for release in step.get("materialization_budget", {}).get("releases", [])
    )
