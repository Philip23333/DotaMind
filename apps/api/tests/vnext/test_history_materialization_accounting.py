from __future__ import annotations

import json

from pydantic import BaseModel

from app.vnext.agent.runtime import _initial_materialization_entries
from app.vnext.llm.protocol import AssistantMessage, Message, ToolCall, ToolResultMessage
from app.vnext.tools import ToolContextEffect, ToolDefinition, ToolRegistry


class _ToolInput(BaseModel):
    value: str = ""


class _ToolOutput(BaseModel):
    value: str


def _handler(_: _ToolInput) -> _ToolOutput:
    return _ToolOutput(value="unused")


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for name, context_effect in (
        ("bounded", ToolContextEffect.BOUNDED),
        ("materializing", ToolContextEffect.MATERIALIZING),
    ):
        registry.register(
            ToolDefinition(
                name=name,
                description=name,
                input_model=_ToolInput,
                output_model=_ToolOutput,
                handler=_handler,
                context_effect=context_effect,
            )
        )
    return registry


def _call(name: str, call_id: str = "same") -> ToolCall:
    return ToolCall(id=call_id, name=name)


def _ok_result(call_id: str = "same", content: object | None = None) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=call_id,
        content={"value": "raw"} if content is None else content,
    )


def _failed_result(call_id: str = "same") -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=call_id,
        status="error",
        error={"code": "tool_execution_error", "message": "failed", "details": {}},
    )


def _messages(*pairs: tuple[ToolCall, ToolResultMessage]) -> list[Message]:
    messages: list[Message] = []
    for call, result in pairs:
        messages.extend((AssistantMessage(tool_calls=[call]), result))
    return messages


def _serialized_bytes(result: ToolResultMessage) -> int:
    return len(
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def test_failed_bounded_result_consumes_same_id_name_before_materializing_success() -> None:
    success = _ok_result()
    messages = _messages(
        (_call("bounded"), _failed_result()),
        (_call("materializing"), success),
    )

    entries = _initial_materialization_entries(messages, _registry())

    assert entries == [("history:3:same", _serialized_bytes(success))]


def test_failed_materializing_result_consumes_same_id_name_before_bounded_success() -> None:
    messages = _messages(
        (_call("materializing"), _failed_result()),
        (_call("bounded"), _ok_result()),
    )

    assert _initial_materialization_entries(messages, _registry()) == []


def test_two_successful_materializing_results_same_id_get_distinct_history_keys() -> None:
    first = _ok_result(content={"value": "first"})
    second = _ok_result(content={"value": "second"})
    messages = _messages(
        (_call("materializing"), first),
        (_call("materializing"), second),
    )

    entries = _initial_materialization_entries(messages, _registry())

    assert entries == [
        ("history:1:same", _serialized_bytes(first)),
        ("history:3:same", _serialized_bytes(second)),
    ]
    assert entries[0][0] != entries[1][0]


def test_receipt_only_materializing_result_does_not_count_as_raw_history() -> None:
    receipt = _ok_result(
        content={
            "_artifact_observation": {
                "state": "receipt_only",
                "ref": "artifact:test",
            }
        }
    )
    messages = _messages((_call("materializing"), receipt))

    assert _initial_materialization_entries(messages, _registry()) == []


def test_request_start_uses_history_and_current_keys_for_same_tool_call_id() -> None:
    historical_call = _call("materializing", "same")
    current_call = _call("materializing", "same")
    messages = _messages(
        (historical_call, _ok_result("same", {"value": "historical"})),
        (current_call, _ok_result("same", {"value": "current"})),
    )

    entries = _initial_materialization_entries(
        messages,
        _registry(),
        request_start=2,
    )

    assert [key for key, _ in entries] == ["history:1:same", "current:same"]


def test_deferred_materializing_result_is_not_rebuilt_as_active_raw() -> None:
    deferred = _ok_result(
        content={
            "_context_materialization": {
                "state": "deferred",
                "reason": "budget_exceeded",
            }
        }
    )
    messages = _messages((_call("materializing"), deferred))

    assert _initial_materialization_entries(messages, _registry()) == []
