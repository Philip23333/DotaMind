"""Durable chat repository contract and stable persistence DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.agentic.conversation.models import ConversationMessage
from app.application.chat_run_repository import ChatRunStatus


class ChatRepositoryError(RuntimeError):
    """Infrastructure failure while reading or writing durable chat data."""

    def __init__(self, code: str = "unavailable") -> None:
        super().__init__(code)
        self.code = code


class ChatNotFoundError(ChatRepositoryError):
    def __init__(self) -> None:
        super().__init__("not_found")


class ChatIdempotencyConflictError(ChatRepositoryError):
    def __init__(self) -> None:
        super().__init__("idempotency_conflict")


class ChatFencingLostError(ChatRepositoryError):
    def __init__(self) -> None:
        super().__init__("fencing_lost")


@dataclass(frozen=True)
class ChatActiveRunSummary:
    run_id: UUID
    status: ChatRunStatus
    last_event_sequence: int
    error_code: str | None


@dataclass(frozen=True)
class ChatSessionSummary:
    session_id: UUID
    game: str
    title: str
    title_is_custom: bool
    is_pinned: bool
    created_at: datetime
    updated_at: datetime
    active_run: ChatActiveRunSummary | None = None


@dataclass(frozen=True)
class ChatTranscriptTurn:
    turn_index: int
    request_id: UUID
    user_query: str
    public_response: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class ChatSessionSnapshot:
    summary: ChatSessionSummary
    turns: list[ChatTranscriptTurn]


@dataclass(frozen=True)
class ChatConversationContext:
    recent_messages: list[ConversationMessage]
    next_turn_index: int


@dataclass(frozen=True)
class ChatRequestLookup:
    status: Literal["missing", "replay"]
    public_response: dict[str, Any] | None = None


@dataclass(frozen=True)
class ChatCommitResult:
    status: Literal["executed", "replay"]
    turn_index: int
    public_response: dict[str, Any]
    session_summary: ChatSessionSummary | None = None


@dataclass(frozen=True)
class ChatDialogueTurnResult:
    """The narrow durable result required by the product chat bridge."""

    status: Literal["executed", "replay"]
    turn_index: int
    assistant_message: str
    catalog_visual_entities: list[dict[str, Any]] = field(default_factory=list)
