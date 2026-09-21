"""Small process-local execution history for one product chat session."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID, uuid4

from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    Message,
    ToolResultMessage,
    UserMessage,
)

RecordKind = Literal[
    "user",
    "assistant_tool_call",
    "execution_final",
    "tool_result",
    "delivery_answer",
]


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """An append-only copy of one message that actually occurred."""

    record_id: str
    request_id: UUID
    sequence: int
    kind: RecordKind
    message: Message
    tool_call_ids: tuple[str, ...] = ()
    status: str | None = None
    context_content: Any = None


class SessionExecutionHistory:
    """Keep immutable raw records beside a replaceable effective projection."""

    def __init__(self) -> None:
        self._records: list[ExecutionRecord] = []
        self._effective_messages: list[Message] = []
        self._request_ids: set[UUID] = set()
        self._sequence = 0
        self._initialized = False

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def records(self) -> tuple[ExecutionRecord, ...]:
        return tuple(
            ExecutionRecord(
                record_id=record.record_id,
                request_id=record.request_id,
                sequence=record.sequence,
                kind=record.kind,
                message=record.message.model_copy(deep=True),
                tool_call_ids=record.tool_call_ids,
                status=record.status,
                context_content=deepcopy(record.context_content),
            )
            for record in self._records
        )

    def effective_messages(self) -> list[Message]:
        return [message.model_copy(deep=True) for message in self._effective_messages]

    def begin_request(
        self,
        request_id: UUID,
        query: str,
        *,
        initial_messages: list[Message] | None = None,
    ) -> list[Message]:
        """Start a request without rebuilding an already-active session."""

        if not self._initialized:
            self._effective_messages = [
                message.model_copy(deep=True)
                for message in (initial_messages or [])
            ]
            self._initialized = True

        if request_id not in self._request_ids:
            self._request_ids.add(request_id)
            current = UserMessage(content=query)
            # ConversationContextBuilder includes the bootstrap query.  For a
            # live session the query is appended here exactly once.
            if not self._effective_messages or self._effective_messages[-1] != current:
                self._effective_messages.append(current)
            self.record(request_id, current, kind="user")
        return self.effective_messages()

    def set_effective(self, messages: list[Message]) -> None:
        """Replace only the model-visible projection with defensive copies."""

        self._effective_messages = [message.model_copy(deep=True) for message in messages]

    def record(
        self,
        request_id: UUID,
        message: Message,
        *,
        kind: RecordKind,
        context_content: Any = None,
    ) -> ExecutionRecord:
        self._sequence += 1
        tool_call_ids = (
            tuple(call.id for call in message.tool_calls)
            if isinstance(message, AssistantMessage)
            else ()
        )
        tool_call_id = (
            (message.tool_call_id,) if isinstance(message, ToolResultMessage) else tool_call_ids
        )
        record = ExecutionRecord(
            record_id=f"record:{uuid4().hex}",
            request_id=request_id,
            sequence=self._sequence,
            kind=kind,
            message=message.model_copy(deep=True),
            tool_call_ids=tool_call_id,
            status=message.status if isinstance(message, ToolResultMessage) else None,
            context_content=deepcopy(context_content),
        )
        self._records.append(record)
        return record

    def record_tool_results(
        self,
        request_id: UUID,
        results: list[ToolResultMessage],
    ) -> None:
        for result in results:
            self.record(request_id, result, kind="tool_result")

    def record_delivery(self, request_id: UUID, final: FinalMessage) -> None:
        self.record(request_id, final, kind="delivery_answer")


__all__ = ["ExecutionRecord", "SessionExecutionHistory"]
