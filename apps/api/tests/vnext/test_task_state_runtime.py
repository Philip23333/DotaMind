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
from app.vnext.tools.task import register_task_checkpoint_tool
from tests.vnext.fakes import ScriptedTranscriptModelClient


def _read_registry(coordinator: TaskStateCoordinator) -> ToolRegistry:
    registry = ToolRegistry()

    async def read(args: Any) -> ArtifactReadResult:
        return ArtifactReadResult(
            ref=args.ref,
            path=args.path,
            value=[{"fact": "A"}],
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


def _tool_response(*calls: ToolCall) -> ModelResponse:
    return ModelResponse(message=AssistantMessage(tool_calls=list(calls)))


def _run(
    model: ScriptedTranscriptModelClient,
    coordinator: TaskStateCoordinator,
    *,
    trace: AgentTraceCollector | None = None,
) -> AgentRuntime:
    runtime = AgentRuntime(
        model,
        _read_registry(coordinator),
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
    _run(model, coordinator, trace=trace)

    snapshot = trace.snapshot()
    rewrite = snapshot["steps"][1]["transcript_rewrites"][0]
    assert rewrite["reason"] == "checkpointed"
    assert rewrite["tool_call_id"] == "call-1"
    assert rewrite["checkpoint_id"].startswith("checkpoint:")
    raw_trace_result = snapshot["steps"][1]["tool_results"][0]["result"]
    assert raw_trace_result["tool_call_id"] == "checkpoint-call"
    assert snapshot["steps"][0]["tool_results"][0]["result"]["content"]["value"] == [
        {"fact": "A"}
    ]
