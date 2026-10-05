"""Small process-local execution history for one product chat session."""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from app.vnext.agent.evidence_summary_lifecycle import validate_compaction_cut
from app.vnext.artifacts.grep import ArtifactGrepResult
from app.vnext.artifacts.retrieval import ArtifactReadResult
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    Message,
    RejectedAssistantMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

RecordKind = Literal[
    "user",
    "assistant_tool_call",
    "assistant_rejected",
    "execution_final",
    "tool_result",
    "delivery_answer",
]


class RequestIdempotencyConflict(ValueError):
    """A request id cannot be reused with different input text."""

    code = "idempotency_conflict"

    def __init__(self) -> None:
        super().__init__("request_id has already been used with different inputs")


class SessionCompactionError(ValueError):
    """A compaction state transition failed its atomic preconditions."""

    _messages = {
        "session_not_initialized": "session execution history is not initialized",
        "unknown_request": "request_id is not registered in this session",
        "inactive_request": "request_id is not the current active request",
        "stale_context_revision": "compaction base revision is stale",
        "empty_summary": "compaction summary must not be blank",
        "invalid_effective_history": "effective history does not preserve the current user message",
        "empty_compaction_history": (
            "compaction prefix has no history besides the current user message"
        ),
    }

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(self._messages.get(code, code))


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


@dataclass(frozen=True, slots=True)
class SessionContextSnapshot:
    """A defensive snapshot used to coordinate one compaction attempt."""

    revision: int
    summary: str | None
    messages: list[Message]
    current_request_id: UUID | None
    current_user_message: UserMessage | None
    current_user_index: int | None


@dataclass(frozen=True, slots=True)
class SessionCompactionRecord:
    """One successfully committed replacement of the effective context."""

    compaction_id: str
    request_id: UUID
    base_revision: int
    cut_index: int
    source_message_count: int
    current_user_index_before: int
    previous_compaction_id: str | None
    summary: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ArtifactLocator:
    """A bounded, first-seen locator for one session-owned Artifact."""

    ref: str
    source_tool: str
    query_hint: str


class SessionExecutionHistory:
    """Keep immutable raw records beside a replaceable effective projection."""

    def __init__(
        self,
        *,
        artifact_locator_capacity: int = 16,
        artifact_locator_hint_chars: int = 256,
    ) -> None:
        if type(artifact_locator_capacity) is not int or artifact_locator_capacity <= 0:
            raise ValueError("artifact_locator_capacity must be a positive integer")
        if type(artifact_locator_hint_chars) is not int or artifact_locator_hint_chars <= 0:
            raise ValueError("artifact_locator_hint_chars must be a positive integer")
        self._records: list[ExecutionRecord] = []
        self._effective_messages: list[Message] = []
        self._request_queries: dict[UUID, str] = {}
        self._sequence = 0
        self._initialized = False
        self._summary: str | None = None
        self._revision = 0
        self._current_request_id: UUID | None = None
        self._current_user_index: int | None = None
        self._compaction_records: list[SessionCompactionRecord] = []
        self._artifact_locator_capacity = artifact_locator_capacity
        self._artifact_locator_hint_chars = artifact_locator_hint_chars
        self._artifact_locators: OrderedDict[str, ArtifactLocator] = OrderedDict()

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def summary(self) -> str | None:
        return self._summary

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def compaction_records(self) -> tuple[SessionCompactionRecord, ...]:
        return tuple(_copy_compaction_record(record) for record in self._compaction_records)

    @property
    def artifact_locators(self) -> tuple[ArtifactLocator, ...]:
        return tuple(self._artifact_locators.values())

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
        return _copy_messages(self._effective_messages)

    def context_snapshot(self) -> SessionContextSnapshot:
        """Return a fixed, defensive view of the current effective context."""

        return SessionContextSnapshot(
            revision=self._revision,
            summary=self._summary,
            messages=_copy_messages(self._effective_messages),
            current_request_id=self._current_request_id,
            current_user_message=self._current_user_message_copy(),
            current_user_index=self._current_user_index,
        )

    def begin_request(
        self,
        request_id: UUID,
        query: str,
        *,
        initial_messages: list[Message] | None = None,
    ) -> list[Message]:
        """Start a request without rebuilding an already-active session."""

        if request_id in self._request_queries:
            if self._request_queries[request_id] != query:
                raise RequestIdempotencyConflict
            if request_id != self._current_request_id:
                raise SessionCompactionError("inactive_request")
            return self.effective_messages()

        initializing = not self._initialized
        if initializing:
            self._effective_messages = [
                message.model_copy(deep=True)
                for message in (initial_messages or [])
            ]
            self._initialized = True

        self._request_queries[request_id] = query
        current = UserMessage(content=query)
        # ConversationContextBuilder includes the bootstrap query.  Remove
        # that one attached copy only while initializing; every later new
        # request appends its user message even when the text is repeated.
        if not (initializing and initial_messages and initial_messages[-1] == current):
            self._effective_messages.append(current)
        self._current_request_id = request_id
        self._current_user_index = len(self._effective_messages) - 1
        self.record(request_id, current, kind="user")
        self._revision += 1
        return self.effective_messages()

    def set_effective(self, messages: list[Message]) -> None:
        """Replace only the model-visible projection with defensive copies."""

        if self._initialized and self._current_user_index is not None:
            if not self._preserves_current_user(messages):
                raise SessionCompactionError("invalid_effective_history")
        copied_messages = _copy_messages(messages)
        self._effective_messages = copied_messages
        self._revision += 1

    def _current_user_message_copy(self) -> UserMessage | None:
        if self._current_request_id is None:
            return None
        query = self._request_queries.get(self._current_request_id)
        return UserMessage(content=query) if query is not None else None

    def _preserves_current_user(self, messages: Sequence[Message]) -> bool:
        index = self._current_user_index
        if index is None or len(messages) < len(self._effective_messages):
            return False
        if index >= len(messages):
            return False
        current = messages[index]
        query = (
            self._request_queries.get(self._current_request_id)
            if self._current_request_id is not None
            else None
        )
        return isinstance(current, UserMessage) and query is not None and current.content == query

    def remember_artifact_locators(
        self,
        call: ToolCall,
        result: ToolResultMessage,
    ) -> None:
        """Remember valid session Artifact refs from one real tool return."""

        if result.tool_call_id != call.id or result.status != "ok":
            return
        refs = _artifact_refs(call, result)
        if not refs:
            return
        query_hint = _query_hint(call.arguments, self._artifact_locator_hint_chars)
        for ref in refs:
            if ref in self._artifact_locators:
                continue
            self._artifact_locators[ref] = ArtifactLocator(
                ref=ref,
                source_tool=call.name,
                query_hint=query_hint,
            )
            if len(self._artifact_locators) > self._artifact_locator_capacity:
                self._artifact_locators.popitem(last=False)

    def commit_compaction(
        self,
        *,
        request_id: UUID,
        base_revision: int,
        summary: str,
        cut_index: int,
    ) -> SessionCompactionRecord:
        """Atomically replace effective history at one validated cut point."""

        if not self._initialized:
            raise SessionCompactionError("session_not_initialized")
        if request_id not in self._request_queries:
            raise SessionCompactionError("unknown_request")
        if request_id != self._current_request_id:
            raise SessionCompactionError("inactive_request")
        if base_revision != self._revision:
            raise SessionCompactionError("stale_context_revision")
        if not summary.strip():
            raise SessionCompactionError("empty_summary")
        current_user_index, current_user_message = self._validated_current_user()

        validate_compaction_cut(self._effective_messages, cut_index=cut_index)
        prefix_history_count = cut_index - (1 if current_user_index < cut_index else 0)
        if prefix_history_count < 1:
            raise SessionCompactionError("empty_compaction_history")

        source_message_count = len(self._effective_messages)
        retained = _copy_messages(self._effective_messages[cut_index:])
        if current_user_index < cut_index:
            copied_messages = [current_user_message, *retained]
            next_current_user_index = 0
        else:
            copied_messages = retained
            next_current_user_index = current_user_index - cut_index

        copied_messages = _copy_messages(copied_messages)
        next_revision = self._revision + 1
        record = SessionCompactionRecord(
            compaction_id=f"compaction:{uuid4().hex}",
            request_id=request_id,
            base_revision=base_revision,
            cut_index=cut_index,
            source_message_count=source_message_count,
            current_user_index_before=current_user_index,
            previous_compaction_id=(
                self._compaction_records[-1].compaction_id
                if self._compaction_records
                else None
            ),
            summary=summary,
            created_at=datetime.now(UTC),
        )

        self._summary = summary
        self._effective_messages = copied_messages
        self._current_user_index = next_current_user_index
        self._revision = next_revision
        self._compaction_records.append(record)
        return _copy_compaction_record(record)

    def _validated_current_user(self) -> tuple[int, UserMessage]:
        index = self._current_user_index
        if index is None or not self._preserves_current_user(self._effective_messages):
            raise SessionCompactionError("invalid_effective_history")
        current = self._effective_messages[index]
        assert isinstance(current, UserMessage)
        return index, current.model_copy(deep=True)

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
            if isinstance(message, AssistantMessage | RejectedAssistantMessage)
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


def _copy_messages(messages: Sequence[Message]) -> list[Message]:
    return [message.model_copy(deep=True) for message in messages]


def _copy_compaction_record(record: SessionCompactionRecord) -> SessionCompactionRecord:
    return SessionCompactionRecord(
        compaction_id=record.compaction_id,
        request_id=record.request_id,
        base_revision=record.base_revision,
        cut_index=record.cut_index,
        source_message_count=record.source_message_count,
        current_user_index_before=record.current_user_index_before,
        previous_compaction_id=record.previous_compaction_id,
        summary=record.summary,
        created_at=record.created_at,
    )


def _artifact_refs(call: ToolCall, result: ToolResultMessage) -> tuple[str, ...]:
    content = result.content
    if call.name == "artifact.read":
        try:
            artifact = ArtifactReadResult.model_validate(content)
        except (TypeError, ValueError):
            return ()
        return (artifact.ref,) if _is_session_artifact_ref(artifact.ref) else ()
    if call.name == "artifact.grep":
        try:
            artifact = ArtifactGrepResult.model_validate(content)
        except (TypeError, ValueError):
            return ()
        refs: list[str] = []
        seen: set[str] = set()
        for match in artifact.matches:
            if _is_session_artifact_ref(match.ref) and match.ref not in seen:
                seen.add(match.ref)
                refs.append(match.ref)
        return tuple(refs)
    if not isinstance(content, dict):
        return ()
    ref = content.get("artifact_ref")
    if content.get("externalized") is True and isinstance(ref, str):
        return (ref,) if _is_session_artifact_ref(ref) else ()
    return ()


def _is_session_artifact_ref(ref: str) -> bool:
    prefix = "artifact:tool:"
    token = ref[len(prefix) :]
    return (
        ref.startswith(prefix)
        and len(token) == 32
        and all(character in "0123456789abcdef" for character in token)
    )


def _query_hint(arguments: dict[str, Any], limit: int) -> str:
    try:
        encoded = json.dumps(
            arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return ""
    return encoded[:limit]


__all__ = [
    "ArtifactLocator",
    "ExecutionRecord",
    "RequestIdempotencyConflict",
    "SessionCompactionError",
    "SessionCompactionRecord",
    "SessionContextSnapshot",
    "SessionExecutionHistory",
]
