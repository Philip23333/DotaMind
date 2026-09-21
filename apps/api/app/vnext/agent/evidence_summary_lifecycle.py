"""Deterministic, protocol-safe history range selection."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.vnext.agent.evidence_summary import HistoryCompactionRange
from app.vnext.agent.instructions import COMPACTION_INSTRUCTION
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    Message,
    ModelRequest,
    ModelResponse,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
)


class HistoryCompactionRangeError(ValueError):
    """The effective history cannot be safely split for compaction."""

    _messages = {
        "invalid_recent_history_budget": "recent history budget must be a positive integer",
        "invalid_history_structure": "history contains an invalid or incomplete message structure",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(self._messages.get(code, code))


class CompactionSummaryError(ValueError):
    """A compaction request or response violated its explicit contract."""

    _messages = {
        "invalid_summary_budget": "summary byte budget must be a positive integer",
        "empty_compaction_history": "compaction history must contain source material",
        "invalid_current_user_position": "current user position is not valid for compaction",
        "summary_input_too_large": "compaction request exceeds its input byte budget",
        "invalid_summary_response": "compaction response must be a final message",
        "summary_output_truncated": "compaction summary was truncated",
        "summary_completion_unconfirmed": "compaction completion was not confirmed",
        "empty_summary": "compaction summary must not be blank",
        "summary_output_too_large": "compaction summary exceeds its output byte budget",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(self._messages.get(code, code))


@dataclass(frozen=True, slots=True)
class _MessageGroup:
    messages: tuple[Message, ...]
    serialized_bytes: int


def select_compaction_range(
    messages: Sequence[Message],
    *,
    recent_history_bytes: int,
) -> HistoryCompactionRange | None:
    """Select a complete older prefix and complete recent suffix.

    The result is only a contiguous range candidate. Later orchestration must
    keep the current user message fixed and construct the summary input without
    duplicating it; this function deliberately treats every ``UserMessage`` as
    ordinary history and never commits a compaction.
    """

    if type(recent_history_bytes) is not int or recent_history_bytes <= 0:
        raise HistoryCompactionRangeError("invalid_recent_history_budget")

    groups = _group_history(messages)
    if len(groups) <= 1:
        return None

    first_retained_group = len(groups) - 1
    retained_bytes = groups[first_retained_group].serialized_bytes
    while retained_bytes < recent_history_bytes and first_retained_group > 0:
        first_retained_group -= 1
        retained_bytes += groups[first_retained_group].serialized_bytes

    cut_index = sum(len(group.messages) for group in groups[:first_retained_group])
    if cut_index <= 0:
        return None

    prefix = tuple(
        message.model_copy(deep=True)
        for group in groups[:first_retained_group]
        for message in group.messages
    )
    retained = tuple(
        message.model_copy(deep=True)
        for group in groups[first_retained_group:]
        for message in group.messages
    )
    return HistoryCompactionRange(
        cut_index=cut_index,
        prefix_messages=prefix,
        retained_messages=retained,
        retained_bytes=retained_bytes,
    )


def _group_history(messages: Sequence[Message]) -> list[_MessageGroup]:
    source = list(messages)
    groups: list[_MessageGroup] = []
    index = 0
    while index < len(source):
        message = source[index]
        if isinstance(message, SystemMessage):
            raise HistoryCompactionRangeError("invalid_history_structure")
        if isinstance(message, UserMessage | FinalMessage):
            groups.append(_make_group((message,)))
            index += 1
            continue
        if isinstance(message, ToolResultMessage):
            raise HistoryCompactionRangeError("invalid_history_structure")
        if not isinstance(message, AssistantMessage):
            raise HistoryCompactionRangeError("invalid_history_structure")
        if not message.tool_calls:
            groups.append(_make_group((message,)))
            index += 1
            continue

        call_ids = [call.id for call in message.tool_calls]
        if len(set(call_ids)) != len(call_ids):
            raise HistoryCompactionRangeError("invalid_history_structure")
        expected = set(call_ids)
        results: list[ToolResultMessage] = []
        result_ids: set[str] = set()
        for _ in call_ids:
            result_index = index + 1 + len(results)
            if result_index >= len(source):
                raise HistoryCompactionRangeError("invalid_history_structure")
            result = source[result_index]
            if not isinstance(result, ToolResultMessage):
                raise HistoryCompactionRangeError("invalid_history_structure")
            if result.tool_call_id not in expected or result.tool_call_id in result_ids:
                raise HistoryCompactionRangeError("invalid_history_structure")
            result_ids.add(result.tool_call_id)
            results.append(result)
        if result_ids != expected:
            raise HistoryCompactionRangeError("invalid_history_structure")
        groups.append(_make_group((message, *results)))
        index += 1 + len(results)
    return groups


def _make_group(messages: tuple[Message, ...]) -> _MessageGroup:
    return _MessageGroup(
        messages=messages,
        serialized_bytes=sum(_message_bytes(message) for message in messages),
    )


def _message_bytes(message: Message) -> int:
    try:
        payload: Any = message.model_dump(mode="json")
        return len(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    except (TypeError, ValueError) as exc:
        raise HistoryCompactionRangeError("invalid_history_structure") from exc


def build_compaction_request(
    *,
    previous_summary: str | None,
    current_user_message: UserMessage,
    prefix_messages: Sequence[Message],
    current_user_prefix_index: int | None,
    max_input_bytes: int,
    max_output_tokens: int,
) -> ModelRequest:
    """Build the model-only request used to replace one active summary."""

    _validate_summary_budget(max_input_bytes)
    _validate_summary_budget(max_output_tokens)
    if not prefix_messages:
        raise CompactionSummaryError("empty_compaction_history")

    # The selector owns the canonical message-group validation.  Its result is
    # intentionally ignored because this function receives the already chosen
    # prefix and must not select or split it again.
    select_compaction_range(prefix_messages, recent_history_bytes=1)

    history = list(prefix_messages)
    if current_user_prefix_index is not None:
        if (
            type(current_user_prefix_index) is not int
            or current_user_prefix_index < 0
            or current_user_prefix_index >= len(history)
        ):
            raise CompactionSummaryError("invalid_current_user_position")
        indexed_message = history[current_user_prefix_index]
        if not isinstance(indexed_message, UserMessage) or indexed_message != current_user_message:
            raise CompactionSummaryError("invalid_current_user_position")
        history.pop(current_user_prefix_index)

    if not history:
        raise CompactionSummaryError("empty_compaction_history")

    payload = {
        "current_user_message": current_user_message.content,
        "previous_summary": previous_summary,
        "history": [message.model_dump(mode="json") for message in history],
    }
    serialized_payload = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    request = ModelRequest(
        messages=[
            SystemMessage(content=COMPACTION_INSTRUCTION),
            UserMessage(content=serialized_payload),
        ],
        tools=[],
        step=None,
        metadata={"purpose": "context_compaction"},
        max_output_tokens=max_output_tokens,
    )
    if _serialized_request_bytes(request) > max_input_bytes:
        raise CompactionSummaryError("summary_input_too_large")
    return request


def validate_compaction_response(
    response: ModelResponse,
    *,
    max_summary_bytes: int,
) -> str:
    """Validate one complete, bounded summary response without rewriting it."""

    _validate_summary_budget(max_summary_bytes)
    if not isinstance(response.message, FinalMessage):
        raise CompactionSummaryError("invalid_summary_response")
    if response.finish_reason == "length":
        raise CompactionSummaryError("summary_output_truncated")
    if response.finish_reason != "stop":
        raise CompactionSummaryError("summary_completion_unconfirmed")
    summary = response.message.content
    if not summary.strip():
        raise CompactionSummaryError("empty_summary")
    if len(summary.encode("utf-8")) > max_summary_bytes:
        raise CompactionSummaryError("summary_output_too_large")
    return summary


def _validate_summary_budget(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise CompactionSummaryError("invalid_summary_budget")


def _serialized_request_bytes(request: ModelRequest) -> int:
    serialized = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return len(serialized.encode("utf-8"))


__all__ = [
    "CompactionSummaryError",
    "HistoryCompactionRangeError",
    "build_compaction_request",
    "select_compaction_range",
    "validate_compaction_response",
]
