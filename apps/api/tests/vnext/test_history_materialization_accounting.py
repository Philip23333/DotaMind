from __future__ import annotations

from pydantic import BaseModel

from app.vnext.agent.runtime import _retained_current_materializing_call_ids
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


def _retained(messages: list[Message], *, request_start: int = 0) -> set[str]:
    return _retained_current_materializing_call_ids(
        messages,
        _registry(),
        request_start=request_start,
    )


def test_failed_result_consumes_matching_call_name_in_fifo_order() -> None:
    messages = _messages(
        (_call("bounded"), _failed_result()),
        (_call("materializing"), _ok_result()),
    )

    assert _retained(messages) == {"same"}


def test_failed_materializing_result_does_not_match_later_bounded_result() -> None:
    messages = _messages(
        (_call("materializing"), _failed_result()),
        (_call("bounded"), _ok_result()),
    )

    assert _retained(messages) == set()


def test_prior_request_result_with_reused_id_is_not_current_evidence() -> None:
    messages = _messages(
        (_call("materializing"), _ok_result(content={"value": "historical"})),
        (_call("bounded"), _ok_result(content={"value": "not materializing"})),
    )

    assert _retained(messages, request_start=2) == set()


def test_current_result_with_reused_id_is_associated_after_historical_result() -> None:
    messages = _messages(
        (_call("materializing"), _ok_result(content={"value": "historical"})),
        (_call("materializing"), _ok_result(content={"value": "current"})),
    )

    assert _retained(messages, request_start=2) == {"same"}


def test_receipts_previews_deferred_results_and_errors_are_not_retained() -> None:
    ineligible = [
        {
            "_artifact_observation": {
                "state": "receipt_only",
                "ref": "artifact:test",
            }
        },
        {"externalized": True, "artifact_ref": "artifact:test", "value": {}},
        {"value": {"_artifact_path": "rows.0"}},
        {"_context_materialization": {"state": "deferred"}},
        None,
    ]
    messages: list[Message] = []
    for index, content in enumerate(ineligible):
        call_id = f"call-{index}"
        call = _call("materializing", call_id)
        result = _failed_result(call_id) if content is None else _ok_result(call_id, content)
        messages.extend((AssistantMessage(tool_calls=[call]), result))

    assert _retained(messages) == set()
