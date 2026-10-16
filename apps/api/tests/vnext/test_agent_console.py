from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pydantic import BaseModel

from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.artifacts import ArtifactObservationTranscriptRewriter
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelResponse,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.vnext.tools.calculate import register_calculate_tool
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry
from scripts.vnext_agent_console import (
    _build_tracing_runtime,
    _console_text,
    _ConversationTrace,
    _run_turn,
    _trace_rows,
    _TracingModelClient,
    _TracingToolRegistry,
)
from tests.vnext.fakes import ScriptedModelClient


def test_console_trace_preserves_full_tool_results_for_debugging(tmp_path: Path) -> None:
    call = ToolCall(id="call-1", name="sample.lookup", arguments={"query": "Grand Final"})
    result = ToolResultMessage(
        tool_call_id="call-1",
        content={
            "status": "unique",
            "query": "Grand Final",
            "candidate_count": 0,
            "candidates": [],
            "unwritten": "full artifact body",
        },
    )

    conversation = _ConversationTrace(name="console_contract", result_dir=tmp_path)
    destination = conversation.append_turn(
        prompt="find the match",
        answer="found it",
        terminal_error=None,
        model_steps=1,
        calls=[call],
        results=[result],
        events=[],
        agent_trace={"steps": [{"step": 1}]},
    )

    conversation.append_turn(
        prompt="follow up",
        answer="done",
        terminal_error=None,
        model_steps=1,
        calls=[],
        results=[],
        events=[],
        agent_trace={"steps": [{"step": 1, "terminal": "final"}]},
    )

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["name"] == "console_contract"
    assert len(payload["turns"]) == 2
    assert payload["turns"][0]["terminal_status"] == "final"
    assert payload["turns"][0]["answer"] == "found it"
    assert payload["turns"][0]["agent_trace"] == {"steps": [{"step": 1}]}
    assert payload["turns"][0]["trace"] == [
        {
            "tool_call_id": "call-1",
            "tool": "sample.lookup",
            "arguments": {"query": "Grand Final"},
            "status": "ok",
            "error": None,
            "result": {
                "status": "unique",
                "query": "Grand Final",
                "candidate_count": 0,
                "candidates": [],
                "unwritten": "full artifact body",
            },
        }
    ]
    assert "full artifact body" in destination.read_text(encoding="utf-8")


def test_console_does_not_replay_runtime_transcript_across_turns(tmp_path: Path) -> None:
    class Input(BaseModel):
        value: int

    class Output(BaseModel):
        value: int

    call = ToolCall(id="call-1", name="test.echo", arguments={"value": 1})
    model = _TracingModelClient(
        ScriptedModelClient(
            [
                ModelResponse(
                    message=AssistantMessage(content=None, tool_calls=[call])
                ),
                ModelResponse(message=FinalMessage(content="final1")),
                ModelResponse(message=FinalMessage(content="answer1")),
                ModelResponse(message=FinalMessage(content="final2")),
                ModelResponse(message=FinalMessage(content="answer2")),
            ]
        )
    )
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="test.echo",
            description="Return the input.",
            input_model=Input,
            output_model=Output,
            handler=lambda args: Output(value=args.value),
        )
    )
    traced_tools = _TracingToolRegistry(registry)
    runtime = AgentRuntime(
        model,
        traced_tools,
        limits=AgentLimits(application_max_output_tokens=4096),
        system_instruction="runtime system",
    )
    conversation = _ConversationTrace(name="two_turns", result_dir=tmp_path)

    async def exercise() -> tuple[
        list[UserMessage | FinalMessage], list[UserMessage | FinalMessage]
    ]:
        _, first_history, _, first_error = await _run_turn(
            runtime,
            model,
            [],
            "user1",
            conversation.name,
            conversation=conversation,
            tool_trace=traced_tools,
        )
        assert first_error is None
        _, second_history, _, second_error = await _run_turn(
            runtime,
            model,
            first_history,
            "user2",
            conversation.name,
            conversation=conversation,
            tool_trace=traced_tools,
        )
        assert second_error is None
        return first_history, second_history

    first_history, second_history = asyncio.run(exercise())

    assert [message.role for message in first_history] == ["user", "final"]
    assert [message.role for message in second_history] == [
        "user",
        "final",
        "user",
        "final",
    ]

    first_turn_requests = model.requests[:2]
    assert isinstance(first_turn_requests[1].messages[-2], AssistantMessage)
    assert first_turn_requests[1].messages[-2].tool_calls
    assert isinstance(first_turn_requests[1].messages[-1], ToolResultMessage)

    second_turn_first_request = model.requests[3]
    assert [message.role for message in second_turn_first_request.messages] == [
        "system",
        "user",
        "final",
        "user",
    ]
    assert sum(
        isinstance(message, SystemMessage)
        for message in second_turn_first_request.messages
    ) == 1
    assert not any(
        isinstance(message, ToolResultMessage)
        for message in second_turn_first_request.messages
    )
    assert not any(
        isinstance(message, AssistantMessage) and message.tool_calls
        for message in second_turn_first_request.messages
    )


def test_console_trace_uses_terminal_tool_event_when_no_next_model_turn() -> None:
    call = ToolCall(id="call-1", name="artifact.read", arguments={"path": "players"})
    events = [
        {
            "kind": "tool_completed",
            "timestamp": "2026-08-27T00:00:00+00:00",
            "step": 8,
            "tool_call_id": "call-1",
            "tool_name": "artifact.read",
            "duration": 0.1,
        }
    ]

    assert _trace_rows([call], [], events) == [
        {
            "tool_call_id": "call-1",
            "tool": "artifact.read",
            "arguments": {"path": "players"},
            "status": "ok",
            "error": None,
            "result": None,
        }
    ]


def test_console_captures_complete_terminal_tool_result_before_next_model_turn() -> None:
    class Input(BaseModel):
        query: str

    class Output(BaseModel):
        full_body: dict[str, list[int]]

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="test.full_result",
            description="Return an uncompressed tool result for console tracing.",
            input_model=Input,
            output_model=Output,
            handler=lambda _args: {"full_body": {"all_values": [1, 2, 3]}},
        )
    )
    traced = _TracingToolRegistry(registry)

    result = asyncio.run(
        traced.execute(
            ToolCall(id="call-terminal", name="test.full_result", arguments={"query": "all"})
        )
    )

    assert result.content == {"full_body": {"all_values": [1, 2, 3]}}
    assert [item.content for item in traced.results] == [result.content]


def test_console_text_replaces_characters_unsupported_by_windows_gbk() -> None:
    assert _console_text("赛事 🏆", encoding="gbk") == "赛事 ?"


def test_console_tracing_runtime_preserves_lifecycle_capabilities() -> None:
    rewriter = ArtifactObservationTranscriptRewriter()
    coordinator = TaskStateCoordinator()
    base_runtime = AgentRuntime(
        ScriptedModelClient([]),
        ToolRegistry(),
        limits=AgentLimits(application_max_output_tokens=4096),
        system_instruction="runtime system",
        shared_instruction="shared product rules",
        transcript_rewriter=rewriter,
        task_state_coordinator=coordinator,
    )
    tracing_model = _TracingModelClient(base_runtime.model)
    tracing_tools = _TracingToolRegistry(base_runtime.tools)

    tracing_runtime = _build_tracing_runtime(
        base_runtime,
        tracing_model,
        tracing_tools,
    )

    assert tracing_runtime.transcript_rewriter is rewriter
    assert tracing_runtime.task_state_coordinator is coordinator
    assert tracing_runtime.shared_instruction == "shared product rules"


def test_console_preserves_shared_instructions_and_answer_tool_execution() -> None:
    registry = ToolRegistry(observation_max_bytes=2048)
    register_calculate_tool(registry)
    call = ToolCall(id="answer-math", name="math.calculate", arguments={"expression": "6 * 7"})
    model = _TracingModelClient(
        ScriptedModelClient(
            [
                ModelResponse.from_final("execution result"),
                ModelResponse(message=AssistantMessage(content=None, tool_calls=[call])),
                ModelResponse.from_final("42"),
            ]
        )
    )
    base = AgentRuntime(
        model,
        registry,
        limits=AgentLimits(application_max_output_tokens=4096),
        shared_instruction="shared product rules",
    )
    traced_tools = _TracingToolRegistry(registry)
    runtime = _build_tracing_runtime(base, model, traced_tools)

    final = asyncio.run(runtime.run([UserMessage(content="calculate")]))

    assert final.content == "42"
    assert len(model.requests) == 3
    assert all(
        any(
            isinstance(m, SystemMessage) and "shared product rules" in m.content for m in r.messages
        )
        for r in model.requests
    )
    assert [tool.name for tool in model.requests[1].tools] == ["math.calculate"]
    assert any(
        isinstance(m, SystemMessage) and "2048 UTF-8 bytes" in m.content
        for m in model.requests[1].messages
    )
    assert traced_tools.results[0].content["result"] == 42
