"""Public request/response contracts for durable Chat Runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ChatRunStatus = Literal[
    "queued",
    "running",
    "waiting_input",
    "cancel_requested",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
]


class ChatRunCreateRequest(BaseModel):
    request_id: UUID
    query: str = Field(min_length=1, max_length=20_000)
    game: Literal["dota2"] = "dota2"


class ChatRunResponse(BaseModel):
    run_id: UUID
    session_id: UUID
    request_id: UUID
    status: ChatRunStatus
    user_query: str = Field(min_length=1)
    last_event_sequence: int = Field(ge=0)
    result_turn_id: UUID | None = None
    error_code: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    completed_at: datetime | None = None


class ChatRunCreateResponse(BaseModel):
    run: ChatRunResponse


class ChatRunActiveResponse(BaseModel):
    run: ChatRunResponse | None


class ChatRunEventResponse(BaseModel):
    run_id: UUID
    session_id: UUID
    sequence: int = Field(ge=1)
    event: dict[str, Any]


class ChatRunHeartbeatResponse(BaseModel):
    type: Literal["heartbeat"] = "heartbeat"
    run_id: UUID
    session_id: UUID
    status: ChatRunStatus
    last_event_sequence: int = Field(ge=0)


class ChatRunStreamErrorResponse(BaseModel):
    type: Literal["error"] = "error"
    run_id: UUID
    session_id: UUID
    error_code: str


class ChatRunCancelResponse(BaseModel):
    run: ChatRunResponse


class ChatRunResumeRequest(BaseModel):
    """Select one option from the Run's persisted Checkpoint."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_type: str = Field(min_length=1)
    option_id: str = Field(min_length=1)


class ChatRunResumeResponse(BaseModel):
    run: ChatRunResponse


class ChatRunErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    error_code: str
    reason: str
