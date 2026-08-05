"""Public schemas for anonymous browser chat management."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ChatSessionCreateRequest(BaseModel):
    game: Literal["dota2"] = "dota2"


class ChatSessionUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    is_pinned: bool | None = None

    @model_validator(mode="after")
    def require_update(self) -> ChatSessionUpdateRequest:
        if self.title is None and self.is_pinned is None:
            raise ValueError("title or is_pinned is required")
        return self


class ChatSessionSummaryResponse(BaseModel):
    session_id: UUID
    game: Literal["dota2"]
    title: str
    title_is_custom: bool
    is_pinned: bool
    created_at: datetime
    updated_at: datetime


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionSummaryResponse]


class ChatTranscriptTurnResponse(BaseModel):
    turn_index: int
    request_id: UUID
    user_query: str
    public_response: dict[str, Any]
    created_at: datetime


class ChatSessionResponse(BaseModel):
    session: ChatSessionSummaryResponse
    turns: list[ChatTranscriptTurnResponse]


class ChatErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    error_code: str
    reason: str
