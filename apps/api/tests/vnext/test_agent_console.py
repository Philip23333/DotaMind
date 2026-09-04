from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pydantic import BaseModel

from app.vnext.llm.protocol import ToolCall, ToolResultMessage
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry
from scripts.vnext_agent_console import (
    _console_text,
    _ConversationTrace,
    _trace_rows,
    _TracingToolRegistry,
)


def test_console_conversation_preserves_full_tool_results_across_turns(tmp_path: Path) -> None:
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
