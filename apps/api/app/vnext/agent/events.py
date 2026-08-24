"""Ephemeral runtime events.  Persistence and replay are deliberately outside this package."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.vnext.llm.protocol import FinalMessage


class AgentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    step: int | None = Field(default=None, ge=1)

    @property
    def event_type(self) -> str:
        return self.kind

    @property
    def type(self) -> str:
        """Compatibility-friendly spelling for event consumers."""

        return self.kind


class AgentStarted(AgentEvent):
    kind: Literal["agent_started"] = "agent_started"


class ModelRequested(AgentEvent):
    kind: Literal["model_requested"] = "model_requested"
    message_count: int = Field(ge=0)
    tool_count: int = Field(ge=0)


class ModelResponded(AgentEvent):
    kind: Literal["model_responded"] = "model_responded"
    has_tool_calls: bool
    duration: float = Field(ge=0)


class TextDelta(AgentEvent):
    kind: Literal["text_delta"] = "text_delta"
    text: str

    @property
    def delta(self) -> str:
        """A concise alias for consumers that call the fragment a delta."""

        return self.text


class ToolStarted(AgentEvent):
    kind: Literal["tool_started"] = "tool_started"
    tool_call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)


class ToolCompleted(AgentEvent):
    kind: Literal["tool_completed"] = "tool_completed"
    tool_call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    duration: float = Field(ge=0)


class ToolFailed(AgentEvent):
    kind: Literal["tool_failed"] = "tool_failed"
    tool_call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    duration: float = Field(ge=0)
    error_code: str = Field(min_length=1)
    error_message: str = Field(min_length=1)


class AgentCompleted(AgentEvent):
    kind: Literal["agent_completed"] = "agent_completed"
    duration: float = Field(ge=0)
    final: FinalMessage


class AgentCancelled(AgentEvent):
    kind: Literal["agent_cancelled"] = "agent_cancelled"
    error_code: Literal["agent_cancelled"] = "agent_cancelled"
    error_message: str = Field(min_length=1)


class AgentFailed(AgentEvent):
    kind: Literal["agent_failed"] = "agent_failed"
    duration: float = Field(ge=0)
    error_code: str = Field(min_length=1)
    error_message: str = Field(min_length=1)


__all__ = [
    "AgentCancelled",
    "AgentCompleted",
    "AgentEvent",
    "AgentFailed",
    "AgentStarted",
    "ModelRequested",
    "ModelResponded",
    "TextDelta",
    "ToolCompleted",
    "ToolFailed",
    "ToolStarted",
]
