"""Stable product API schemas for request-bound vNext chat."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ChatMessageRequest(BaseModel):
    request_id: UUID
    query: str = Field(min_length=1, max_length=20_000)


class ChatMessageDeltaEvent(BaseModel):
    type: Literal["delta"] = "delta"
    text: str


class ChatMessageCompletedEvent(BaseModel):
    type: Literal["completed"] = "completed"
    content: str
    turn_index: int = Field(ge=1)


class ChatMessageErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    error_code: str
    reason: str
