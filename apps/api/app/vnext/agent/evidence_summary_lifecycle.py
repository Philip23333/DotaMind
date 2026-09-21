"""Deterministic, protocol-safe history range selection."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.vnext.agent.evidence_summary import HistoryCompactionRange
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    Message,
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


__all__ = ["HistoryCompactionRangeError", "select_compaction_range"]
