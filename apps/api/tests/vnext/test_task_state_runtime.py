from __future__ import annotations

import asyncio
from typing import Any

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
    ToolResultMessage,
    UserMessage,
)
from app.vnext.tools import ToolDefinition, ToolRegistry
from app.vnext.tools.task import register_task_checkpoint_tool, register_task_plan_tool
from tests.vnext.fakes import ScriptedTranscriptModelClient


def _read_registry(
    coordinator: TaskStateCoordinator,
    *,
    value: object | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    read_value = value if value is not None else [{"fact": "A"}]

    async def read(args: Any) -> ArtifactReadResult:
        return ArtifactReadResult(
            ref=args.ref,
            path=args.path,
            value=read_value,
            offset=0,
            limit=1,
            total=1,
        )

    from pydantic import BaseModel

    class ReadArguments(BaseModel):
        ref: str
        mode: str
        path: str

    registry.register(
        ToolDefinition(
            name="artifact.read",
            description="read",
            input_model=ReadArguments,
            output_model=ArtifactReadResult,
            handler=read,
            externalize_result=False,
        )
    )
    register_task_plan_tool(registry, coordinator)
    register_task_checkpoint_tool(registry, coordinator)
    return registry


def _read_call(call_id: str = "call-1", path: str = "rows") -> ToolCall:
    return ToolCall(
        id=call_id,
        name="artifact.read",
        arguments={"ref": "artifact:test", "mode": "read", "path": path},
    )


def _checkpoint_call(
    call_id: str,
    *,
    key: str = "part",
    value: dict[str, Any] | None = None,
    source: list[str] | None = None,
) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="task.checkpoint",
        arguments={
            "key": key,
            "value": value or {"fact": "A"},
            "source_tool_call_ids": source or ["call-1"],
        },
    )


def _plan_call(call_id: str = "plan-call") -> ToolCall:
    return ToolCall(
        id=call_id,
        name="task.plan",
        arguments={
            "items": [
                {"key": "2025", "objective": "Collect 2025 evidence"},
                {"key": "2026", "objective": "Collect 2026 evidence"},
            ]
        },
    )


def _tool_response(*calls: ToolCall) -> ModelResponse:
    return ModelResponse(message=AssistantMessage(tool_calls=list(calls)))


def _run(
    model: ScriptedTranscriptModelClient,
    coordinator: TaskStateCoordinator,
    *,
    trace: AgentTraceCollector | None = None,
    read_value: object | None = None,
) -> AgentRuntime:
    runtime = AgentRuntime(
        model,
        _read_registry(coordinator, value=read_value),
        transcript_rewriter=ArtifactObservationTranscriptRewriter(),
        task_state_coordinator=coordinator,
    )
    asyncio.run(runtime.run([UserMessage(content="collect evidence")], trace_collector=trace))
    return runtime


def _system(request: ModelRequest) -> str:
    return next(
        message.content
        for message in request.messages
        if isinstance(message, SystemMessage)
    )


def test_flow_a_manifest_then_checkpoint_state_next_turn_and_raw_preserved() -> None:
    coordinator = TaskStateCoordinator()

    def first(_: ModelRequest) -> ModelResponse:
        return _tool_response(_read_call())

    def second(request: ModelRequest) -> ModelResponse:
        assert '"tool_call_id":"call-1"' in _system(request)
        return _tool_response(_checkpoint_call("checkpoint-call"))

    def third(request: ModelRequest) -> ModelResponse:
        system = _system(request)
        assert '"part":{"fact":"A"}' in system
        assert '"tool_call_id":"call-1"' not in system
        return ModelResponse(message=FinalMessage(content="done"))

    model = ScriptedTranscriptModelClient([first, second, third])
    _run(model, coordinator)

    raw_result = next(
        message
        for message in model.requests[2].messages
        if isinstance(message, ToolResultMessage) and message.tool_call_id == "call-1"
    )
    assert raw_result.content["_artifact_observation"]["reason"] == "checkpointed"  # type: ignore[index]
    assert raw_result.content["_artifact_observation"]["checkpoint_id"].startswith(  # type: ignore[index]
        "checkpoint:"
    )
    assert coordinator.store.get("part") is not None


def test_flow_b_invalid_source_returns_error_leaves_state_empty_and_raw() -> None:
    coordinator = TaskStateCoordinator()

    def first(_: ModelRequest) -> ModelResponse:
        return _tool_response(_read_call())

    def second(request: ModelRequest) -> ModelResponse:
        assert '"tool_call_id":"call-1"' in _system(request)
        return _tool_response(_checkpoint_call("bad", source=["missing"]))

    def third(request: ModelRequest) -> ModelResponse:
        assert "Task state:\n{}" in _system(request)
        assert '"tool_call_id":"call-1"' in _system(request)
        return ModelResponse(message=FinalMessage(content="partial"))

    model = ScriptedTranscriptModelClient([first, second, third])
    _run(model, coordinator)

    assert coordinator.store.snapshot() == {}
    error_result = next(
        message
        for message in model.requests[2].messages
        if isinstance(message, ToolResultMessage) and message.tool_call_id == "bad"
    )
    assert error_result.status == "error"
    raw_result = next(
        message
        for message in model.requests[2].messages
        if isinstance(message, ToolResultMessage) and message.tool_call_id == "call-1"
    )
    assert raw_result.status == "ok"


def test_flow_c_same_key_replaced_and_new_key_is_latest_context() -> None:
    coordinator = TaskStateCoordinator()

    def first(_: ModelRequest) -> ModelResponse:
        return _tool_response(_read_call("call-1", "rows.0"))

    def second(_: ModelRequest) -> ModelResponse:
        return _tool_response(_checkpoint_call("checkpoint-a"))

    def third(_: ModelRequest) -> ModelResponse:
        return _tool_response(_read_call("call-2", "rows.1"))

    def fourth(_: ModelRequest) -> ModelResponse:
        return _tool_response(
            _checkpoint_call(
                "checkpoint-b",
                key="part",
                value={"fact": "B"},
                source=["call-2"],
            )
        )

    def fifth(request: ModelRequest) -> ModelResponse:
        system = _system(request)
        assert '"part":{"fact":"B"}' in system
        assert '"fact":"A"' not in system
        return ModelResponse(message=FinalMessage(content="done"))

    model = ScriptedTranscriptModelClient([first, second, third, fourth, fifth])
    _run(model, coordinator)

    assert [checkpoint.key for checkpoint in coordinator.store.list()] == ["part"]


def test_flow_d_task_context_is_ephemeral_and_does_not_accumulate_in_transcript() -> None:
    coordinator = TaskStateCoordinator()

    def first(_: ModelRequest) -> ModelResponse:
        return _tool_response(_read_call())

    def second(request: ModelRequest) -> ModelResponse:
        assert "Task state:" not in "\n".join(
            message.content
            for message in request.messages
            if not isinstance(message, SystemMessage)
            and hasattr(message, "content")
            and isinstance(message.content, str)
        )
        return _tool_response(_checkpoint_call("checkpoint-call"))

    def third(request: ModelRequest) -> ModelResponse:
        assert _system(request).count("Task state:") == 1
        stable = [message for message in request.messages if not isinstance(message, SystemMessage)]
        assert all(
            not (isinstance(message, ToolResultMessage) and message.content == {"fact": "A"})
            for message in stable
        )
        return ModelResponse(message=FinalMessage(content="done"))

    model = ScriptedTranscriptModelClient([first, second, third])
    _run(model, coordinator)

    assert "Task state:" not in "\n".join(
        message.content
        for message in model.requests[1].messages
        if isinstance(message, UserMessage)
    )


def test_flow_e_checkpoint_rewrite_trace_keeps_raw_tool_result() -> None:
    coordinator = TaskStateCoordinator()
    trace = AgentTraceCollector()

    def first(_: ModelRequest) -> ModelResponse:
        return _tool_response(_read_call())

    def second(_: ModelRequest) -> ModelResponse:
        return _tool_response(_checkpoint_call("checkpoint-call"))

    def third(_: ModelRequest) -> ModelResponse:
        return ModelResponse(message=FinalMessage(content="done"))

    model = ScriptedTranscriptModelClient([first, second, third])
    read_value = [{"fact": "A" * 2000}]
    _run(model, coordinator, trace=trace, read_value=read_value)

    snapshot = trace.snapshot()
    rewrite = snapshot["steps"][1]["transcript_rewrites"][0]
    assert rewrite["reason"] == "checkpointed"
    assert rewrite["tool_call_id"] == "call-1"
    assert rewrite["checkpoint_id"].startswith("checkpoint:")
    checkpoint_metric = snapshot["steps"][1]["checkpoint_metrics"][0]
    assert checkpoint_metric["tool_call_id"] == "checkpoint-call"
    assert checkpoint_metric["status"] == "ok"
    assert checkpoint_metric["checkpoint_id"].startswith("checkpoint:")
    assert checkpoint_metric["key"] == "part"
    assert checkpoint_metric["source_count"] == 1
    assert checkpoint_metric["value_bytes"] > 0
    assert rewrite["raw_bytes"] > rewrite["receipt_bytes"]
    assert rewrite["saved_bytes"] > 0
    raw_trace_result = snapshot["steps"][1]["tool_results"][0]["result"]
    assert raw_trace_result["tool_call_id"] == "checkpoint-call"
    assert snapshot["steps"][0]["tool_results"][0]["result"]["content"]["value"] == read_value
    before = snapshot["steps"][1]["context_accounting"]
    after = snapshot["steps"][2]["context_accounting"]
    assert before["artifact_observations"]["active_raw"]["count"] == 1
    assert before["task_context"]["task_state"]["count"] == 0
    assert after["artifact_observations"]["active_raw"]["count"] == 0
    assert after["artifact_observations"]["receipts"]["count"] == 1
    assert after["task_context"]["task_state"]["count"] == 1
    assert after["task_context"]["task_state"]["serialized_bytes"] > 0
    assert after["task_context"]["active_manifest"]["count"] == 0
    assert after["runtime_prompt"]["serialized_bytes"] > 0
    assert "Task state:" not in str(snapshot["steps"][2]["model_request"])


def test_flow_f_plan_serially_checkpoints_each_result_unit() -> None:
    coordinator = TaskStateCoordinator()
    trace = AgentTraceCollector()

    def first(_: ModelRequest) -> ModelResponse:
        return _tool_response(_plan_call())

    def second(request: ModelRequest) -> ModelResponse:
        system = _system(request)
        assert "CURRENT: 2025" in system
        assert "2026 [pending]" in system
        return _tool_response(_read_call("read-2025", "2025"))

    def third(request: ModelRequest) -> ModelResponse:
        assert "CURRENT: 2025" in _system(request)
        return _tool_response(
            _checkpoint_call(
                "checkpoint-2025", key="2025", source=["read-2025"], value={"year": 2025}
            )
        )

    def fourth(request: ModelRequest) -> ModelResponse:
        system = _system(request)
        assert "CURRENT: 2026" in system
        assert "2025 [completed]" in system
        assert '"2025":{"year":2025}' in system
        assert any(
            isinstance(message, ToolResultMessage)
            and message.tool_call_id == "read-2025"
            and message.content["_artifact_observation"]["state"] == "receipt_only"  # type: ignore[index]
            for message in request.messages
        )
        return _tool_response(_read_call("read-2026", "2026"))

    def fifth(request: ModelRequest) -> ModelResponse:
        assert "CURRENT: 2026" in _system(request)
        return _tool_response(
            _checkpoint_call(
                "checkpoint-2026", key="2026", source=["read-2026"], value={"year": 2026}
            )
        )

    model = ScriptedTranscriptModelClient([first, second, third, fourth, fifth])
    _run(model, coordinator, trace=trace)

    plan = coordinator.plan_snapshot()
    assert plan is not None and plan.current_key is None
    assert all(item.status.value == "completed" for item in plan.items)
    assert coordinator.store.get("2025") is not None
    assert coordinator.store.get("2026") is not None
    snapshot = trace.snapshot()
    assert snapshot["steps"][0]["task_plan_metrics"] == [
        {
            "tool_call_id": "plan-call",
            "status": "ok",
            "item_count": 2,
            "current_key": "2025",
        }
    ]
    assert len(snapshot["steps"][2]["transcript_rewrites"]) == 1
    assert len(snapshot["steps"][4]["transcript_rewrites"]) == 1
    assert snapshot["steps"][2]["transcript_rewrites"][0]["reason"] == "checkpointed"
    assert snapshot["steps"][4]["transcript_rewrites"][0]["reason"] == "checkpointed"
    assert all(
        tool_result["result"]["tool_call_id"] in {"plan-call", "checkpoint-2025", "checkpoint-2026"}
        or tool_result["result"]["tool_call_id"] in {"read-2025", "read-2026"}
        for step in snapshot["steps"]
        for tool_result in step.get("tool_results", [])
    )


def test_flow_g_wrong_plan_key_does_not_advance_or_claim_raw() -> None:
    coordinator = TaskStateCoordinator()

    def first(_: ModelRequest) -> ModelResponse:
        return _tool_response(_plan_call())

    def second(_: ModelRequest) -> ModelResponse:
        return _tool_response(_read_call("read-2025"))

    def third(_: ModelRequest) -> ModelResponse:
        return _tool_response(
            _checkpoint_call(
                "bad-checkpoint", key="2026", source=["read-2025"], value={"year": 2025}
            )
        )

    def fourth(request: ModelRequest) -> ModelResponse:
        system = _system(request)
        assert "CURRENT: 2025" in system
        assert "2025 [in_progress]" in system
        assert "2026 [pending]" in system
        assert "Task state:\n{}" in system
        return ModelResponse(message=FinalMessage(content="incomplete"))

    model = ScriptedTranscriptModelClient([first, second, third, fourth])
    _run(model, coordinator)

    assert coordinator.plan_snapshot().current_key == "2025"  # type: ignore[union-attr]
    assert coordinator.store.snapshot() == {}
    result = next(
        message
        for message in model.requests[3].messages
        if isinstance(message, ToolResultMessage) and message.tool_call_id == "read-2025"
    )
    assert result.content["value"] == [{"fact": "A"}]  # type: ignore[index]


def test_flow_h_invalid_plan_source_does_not_advance_or_claim_raw() -> None:
    coordinator = TaskStateCoordinator()

    def first(_: ModelRequest) -> ModelResponse:
        return _tool_response(_plan_call())

    def second(_: ModelRequest) -> ModelResponse:
        return _tool_response(_read_call("read-2025"))

    def third(_: ModelRequest) -> ModelResponse:
        return _tool_response(
            _checkpoint_call(
                "bad-checkpoint", key="2025", source=["missing"], value={"year": 2025}
            )
        )

    def fourth(request: ModelRequest) -> ModelResponse:
        assert "CURRENT: 2025" in _system(request)
        return ModelResponse(message=FinalMessage(content="incomplete"))

    model = ScriptedTranscriptModelClient([first, second, third, fourth])
    _run(model, coordinator)

    assert coordinator.plan_snapshot().current_key == "2025"  # type: ignore[union-attr]
    assert coordinator.store.snapshot() == {}
