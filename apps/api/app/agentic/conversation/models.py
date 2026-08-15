"""Conversation memory contracts shared by the agentic and application layers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConversationMessage(BaseModel):
    """One real user or assistant message available to the Controller."""

    model_config = ConfigDict(extra="forbid")

    turn_index: int = Field(ge=1)
    role: Literal["user", "assistant"]
    content: str


class ControllerContextExecutionSummary(BaseModel):
    """Minimal completed-tool metadata retained for the next Controller call."""

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1)
    status: Literal["completed"] = "completed"
    matched_turns: int = Field(ge=0)


class DialogueTurn(BaseModel):
    """A complete user/assistant exchange kept together in the recent window."""

    model_config = ConfigDict(extra="forbid")

    turn_index: int = Field(ge=1)
    user_message: str
    assistant_message: str


class RecentDialogueWindow(BaseModel):
    """Bounded, reconstructible Redis cache of complete recent turns."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    through_turn_index: int = Field(ge=0)
    truncated_before: bool = False
    turns: list[DialogueTurn] = Field(default_factory=list)


class Turn(BaseModel):
    """Lossy audit record; it is not the Controller's default conversation input."""

    model_config = ConfigDict(extra="forbid")

    turn_index: int = Field(default=0, ge=0)
    query: str
    status: Literal[
        "ok",
        "clarification_required",
        "insufficient_context",
        "insufficient_tools",
        "insufficient_evidence",
        "error",
    ] = "ok"
    response_type: str | None = None
    intent: str | None = None
    context_scope: dict = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    response_summary: str = ""


__all__ = [
    "ConversationMessage",
    "ControllerContextExecutionSummary",
    "DialogueTurn",
    "RecentDialogueWindow",
    "Turn",
]
