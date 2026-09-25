"""Validated request and state envelopes for the AssistantTransport endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.vnext.product.run_state import ProductRunState


class AssistantTransportTextPart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["text"]
    text: str


class AssistantTransportUserCommandMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user"]
    parts: list[AssistantTransportTextPart]


class AssistantTransportAddMessageCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["add-message"]
    message: AssistantTransportUserCommandMessage
    parent_id: str | None = Field(alias="parentId")
    source_id: str | None = Field(alias="sourceId")


class AssistantTransportRequest(BaseModel):
    """The official command shape plus DotaMind's request id and ignored client state."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    request_id: UUID
    commands: list[AssistantTransportAddMessageCommand]
    state: Any = None
    thread_id: str | None = Field(default=None, alias="threadId")
    # Parent identity locates an ordinary append in assistant-ui too; DotaMind
    # does not use it to replace or branch server-owned history.
    parent_id: str | None = Field(default=None, alias="parentId")
    system: str | None = None
    tools: dict[str, Any] | None = None
    call_settings: dict[str, Any] | None = Field(default=None, alias="callSettings")
    config: dict[str, Any] | None = None

    @model_validator(mode="after")
    def reject_client_model_configuration(self) -> AssistantTransportRequest:
        if self.system not in (None, ""):
            raise ValueError("custom system prompts are not supported")
        if self.tools:
            raise ValueError("client tool definitions are not supported")
        if self.call_settings:
            raise ValueError("client model settings are not supported")
        if self.config:
            raise ValueError("client model configuration is not supported")
        if any(value is not None for value in (self.model_extra or {}).values()):
            raise ValueError("unknown transport request fields are not supported")
        return self


class AssistantTransportUserMessage(BaseModel):
    id: str
    text: str


class AssistantTransportTraceRef(BaseModel):
    trace_id: str
    expires_at: datetime


class AssistantTransportState(BaseModel):
    session_id: UUID
    request_id: UUID
    user_message: AssistantTransportUserMessage
    run: ProductRunState
    turn_index: int | None = None
    trace: AssistantTransportTraceRef | None = None
