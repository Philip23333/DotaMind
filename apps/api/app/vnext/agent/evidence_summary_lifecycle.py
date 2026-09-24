"""Deterministic, protocol-safe history range selection."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.vnext.agent.evidence_summary import CompactionPreparation, HistoryCompactionRange
from app.vnext.agent.instructions import (
    HISTORY_COMPACTION_INSTRUCTION,
    TURN_PREFIX_COMPACTION_INSTRUCTION,
)
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
        "invalid_compaction_boundary": "compaction cut is not a complete message-group boundary",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(self._messages.get(code, code))


class CompactionSummaryError(ValueError):
    """A compaction request or response violated its explicit contract."""

    _messages = {
        "invalid_summary_budget": "compaction budgets must be positive integers",
        "empty_compaction_history": "compaction history must contain source material",
        "invalid_current_user_position": "current user position is not valid for compaction",
        "summary_input_too_large": "compaction request exceeds its input byte budget",
        "invalid_summary_response": "compaction response must be a final message",
        "summary_output_truncated": "compaction summary was truncated",
        "summary_completion_unconfirmed": "compaction completion was not confirmed",
        "empty_summary": "compaction summary must not be blank",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(self._messages.get(code, code))


@dataclass(frozen=True, slots=True)
class _MessageGroup:
    messages: tuple[Message, ...]
    serialized_bytes: int
    estimated_tokens: int


def select_compaction_range(
    messages: Sequence[Message],
    *,
    recent_history_tokens: int,
    bytes_per_token: int,
) -> HistoryCompactionRange | None:
    """Select a complete older prefix and complete recent suffix.

    The result is only a contiguous range candidate. Later orchestration must
    keep the current user message fixed and construct the summary input without
    duplicating it; this function deliberately treats every ``UserMessage`` as
    ordinary history and never commits a compaction.
    """

    if (
        type(recent_history_tokens) is not int
        or recent_history_tokens <= 0
        or type(bytes_per_token) is not int
        or bytes_per_token <= 0
    ):
        raise HistoryCompactionRangeError("invalid_recent_history_budget")

    groups = _group_history(messages, bytes_per_token=bytes_per_token)
    if len(groups) <= 1:
        return None

    first_retained_group = len(groups) - 1
    retained_bytes = groups[first_retained_group].serialized_bytes
    retained_estimated_tokens = groups[first_retained_group].estimated_tokens
    while retained_estimated_tokens < recent_history_tokens and first_retained_group > 0:
        first_retained_group -= 1
        retained_bytes += groups[first_retained_group].serialized_bytes
        retained_estimated_tokens += groups[first_retained_group].estimated_tokens

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
        retained_estimated_tokens=retained_estimated_tokens,
    )


def prepare_compaction(
    messages: Sequence[Message],
    *,
    recent_history_tokens: int,
    bytes_per_token: int,
) -> CompactionPreparation | None:
    """Select a recent suffix and split a cut turn from preceding history."""

    selected = select_compaction_range(
        messages,
        recent_history_tokens=recent_history_tokens,
        bytes_per_token=bytes_per_token,
    )
    if selected is None:
        return None

    split_turn_start_index: int | None = None
    if not isinstance(messages[selected.cut_index], UserMessage):
        for index in range(selected.cut_index - 1, -1, -1):
            message = messages[index]
            if isinstance(message, FinalMessage):
                break
            if isinstance(message, UserMessage):
                split_turn_start_index = index
                break

    if split_turn_start_index is None:
        history = messages[: selected.cut_index]
        turn_prefix: Sequence[Message] = ()
    else:
        history = messages[:split_turn_start_index]
        turn_prefix = messages[split_turn_start_index : selected.cut_index]

    return CompactionPreparation(
        cut_index=selected.cut_index,
        history_messages=tuple(message.model_copy(deep=True) for message in history),
        turn_prefix_messages=tuple(message.model_copy(deep=True) for message in turn_prefix),
        retained_messages=tuple(
            message.model_copy(deep=True) for message in selected.retained_messages
        ),
        split_turn_start_index=split_turn_start_index,
        retained_estimated_tokens=selected.retained_estimated_tokens,
    )


def validate_compaction_cut(
    messages: Sequence[Message],
    *,
    cut_index: int,
) -> None:
    """Validate one caller-provided cut without selecting another boundary."""

    groups = _group_history(messages)
    if type(cut_index) is not int or not 0 < cut_index < len(messages):
        raise HistoryCompactionRangeError("invalid_compaction_boundary")

    boundary = 0
    for group in groups:
        boundary += len(group.messages)
        if boundary == cut_index:
            return
    raise HistoryCompactionRangeError("invalid_compaction_boundary")


def _group_history(messages: Sequence[Message], *, bytes_per_token: int = 1) -> list[_MessageGroup]:
    source = list(messages)
    groups: list[_MessageGroup] = []
    index = 0
    while index < len(source):
        message = source[index]
        if isinstance(message, SystemMessage):
            raise HistoryCompactionRangeError("invalid_history_structure")
        if isinstance(message, UserMessage | FinalMessage):
            groups.append(_make_group((message,), bytes_per_token=bytes_per_token))
            index += 1
            continue
        if isinstance(message, ToolResultMessage):
            raise HistoryCompactionRangeError("invalid_history_structure")
        if not isinstance(message, AssistantMessage):
            raise HistoryCompactionRangeError("invalid_history_structure")
        if not message.tool_calls:
            groups.append(_make_group((message,), bytes_per_token=bytes_per_token))
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
        groups.append(_make_group((message, *results), bytes_per_token=bytes_per_token))
        index += 1 + len(results)
    return groups


def _make_group(messages: tuple[Message, ...], *, bytes_per_token: int) -> _MessageGroup:
    serialized_bytes = sum(_message_bytes(message) for message in messages)
    return _MessageGroup(
        messages=messages,
        serialized_bytes=serialized_bytes,
        estimated_tokens=(serialized_bytes + bytes_per_token - 1) // bytes_per_token,
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


def build_history_compaction_request(
    *,
    previous_summary: str | None,
    history_messages: Sequence[Message],
    max_input_bytes: int,
    max_output_tokens: int,
) -> ModelRequest:
    """Build a request that updates the session's compressed history."""

    _validate_summary_budget(max_input_bytes)
    _validate_summary_budget(max_output_tokens)
    if not history_messages:
        raise CompactionSummaryError("empty_compaction_history")
    _group_history(history_messages)

    payload = {
        "previous_summary": previous_summary,
        "history": [message.model_dump(mode="json") for message in history_messages],
    }
    request = _build_compaction_request(
        instruction=HISTORY_COMPACTION_INSTRUCTION,
        payload=payload,
        kind="history",
        max_input_bytes=max_input_bytes,
        max_output_tokens=max_output_tokens,
    )
    return request


def build_turn_prefix_compaction_request(
    *,
    turn_prefix_messages: Sequence[Message],
    max_input_bytes: int,
    max_output_tokens: int,
) -> ModelRequest:
    """Build a request that summarizes only the cut portion of one turn."""

    _validate_summary_budget(max_input_bytes)
    _validate_summary_budget(max_output_tokens)
    if not turn_prefix_messages:
        raise CompactionSummaryError("empty_compaction_history")
    _group_history(turn_prefix_messages)
    payload = {
        "turn_prefix": [message.model_dump(mode="json") for message in turn_prefix_messages],
    }
    return _build_compaction_request(
        instruction=TURN_PREFIX_COMPACTION_INSTRUCTION,
        payload=payload,
        kind="turn_prefix",
        max_input_bytes=max_input_bytes,
        max_output_tokens=max_output_tokens,
    )


def _build_compaction_request(
    *,
    instruction: str,
    payload: dict[str, Any],
    kind: str,
    max_input_bytes: int,
    max_output_tokens: int,
) -> ModelRequest:
    serialized_payload = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    request = ModelRequest(
        messages=[
            SystemMessage(content=instruction),
            UserMessage(content=serialized_payload),
        ],
        tools=[],
        step=None,
        metadata={"purpose": "context_compaction", "compaction_kind": kind},
        max_output_tokens=max_output_tokens,
    )
    if _serialized_request_bytes(request) > max_input_bytes:
        raise CompactionSummaryError("summary_input_too_large")
    return request


def validate_compaction_response(response: ModelResponse) -> str:
    """Validate one complete summary response without rewriting it."""

    if not isinstance(response.message, FinalMessage):
        raise CompactionSummaryError("invalid_summary_response")
    if response.finish_reason == "length":
        raise CompactionSummaryError("summary_output_truncated")
    if response.finish_reason != "stop":
        raise CompactionSummaryError("summary_completion_unconfirmed")
    summary = response.message.content
    if not summary.strip():
        raise CompactionSummaryError("empty_summary")
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
    "build_history_compaction_request",
    "build_turn_prefix_compaction_request",
    "prepare_compaction",
    "select_compaction_range",
    "validate_compaction_cut",
    "validate_compaction_response",
]
