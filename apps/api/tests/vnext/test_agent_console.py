from __future__ import annotations

import json
from pathlib import Path

from app.vnext.llm.protocol import ToolCall, ToolResultMessage
from scripts.vnext_agent_console import _console_text, _trace_rows, _write_result


def test_console_result_contains_compact_tool_trace(tmp_path: Path) -> None:
    call = ToolCall(id="call-1", name="matches.search", arguments={"query": "Grand Final"})
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

    destination = _write_result(
        name="console_contract",
        prompt="find the match",
        answer="found it",
        terminal_error=None,
        model_steps=1,
        calls=[call],
        results=[result],
        events=[],
        result_dir=tmp_path,
    )

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["terminal_status"] == "final"
    assert payload["answer"] == "found it"
    assert payload["trace"] == [
        {
            "tool": "matches.search",
            "arguments": {"query": "Grand Final"},
            "status": "ok",
            "error": None,
            "result": {
                "status": "unique",
                "query": "Grand Final",
                "candidate_count": 0,
                "candidates": [],
                "candidates_truncated": False,
            },
        }
    ]
    assert "full artifact body" not in destination.read_text(encoding="utf-8")


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
            "tool": "artifact.read",
            "arguments": {"path": "players"},
            "status": "ok",
            "error": None,
            "result": None,
        }
    ]


def test_console_text_replaces_characters_unsupported_by_windows_gbk() -> None:
    assert _console_text("赛事 🏆", encoding="gbk") == "赛事 ?"
