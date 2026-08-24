"""Provider-neutral messages exchanged by the vNext runtime and model client."""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.vnext.agent.errors import ToolError


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SystemMessage(_Message):
    role: Literal["system"] = "system"
    content: str


class UserMessage(_Message):
    role: Literal["user"] = "user"
    content: str


class ToolCall(_Message):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class AssistantMessage(_Message):
    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class ToolResultMessage(_Message):
    role: Literal["tool"] = "tool"
    tool_call_id: str = Field(min_length=1)
    content: Any = None
    status: Literal["ok", "error"] = "ok"
    error: ToolError | None = None

    @model_validator(mode="after")
    def validate_error_shape(self) -> ToolResultMessage:
        if self.status == "error" and self.error is None:
            raise ValueError("error tool results require a structured error")
        if self.status == "ok" and self.error is not None:
            raise ValueError("successful tool results cannot contain an error")
        return self


class FinalMessage(_Message):
    """A terminal assistant response returned by the model client/runtime."""

    role: Literal["final"] = "final"
    content: str


Message = SystemMessage | UserMessage | AssistantMessage | ToolResultMessage | FinalMessage


class ModelRequest(_Message):
    messages: list[Message]
    tools: list[dict[str, Any]] = Field(default_factory=list)
    step: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(_Message):
    """One provider-neutral model turn.

    ``message`` is the canonical field.  ``final`` and ``assistant`` are
    convenience constructor fields for small model fakes and normalize into
    the same canonical message.
    """

    message: AssistantMessage | FinalMessage | None = None
    final: FinalMessage | None = None
    assistant: AssistantMessage | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_message(self) -> ModelResponse:
        candidates = [
            candidate
            for candidate in (self.message, self.final, self.assistant)
            if candidate is not None
        ]
        if len(candidates) != 1:
            raise ValueError("model response must contain exactly one message")
        if self.message is None:
            object.__setattr__(self, "message", candidates[0])
        return self

    @property
    def is_final(self) -> bool:
        return isinstance(self.message, FinalMessage)

    @classmethod
    def from_final(cls, content: str, **kwargs: Any) -> ModelResponse:
        return cls(final=FinalMessage(content=content), **kwargs)

    @classmethod
    def from_assistant(cls, message: AssistantMessage, **kwargs: Any) -> ModelResponse:
        return cls(assistant=message, **kwargs)


@runtime_checkable
class ModelClient(Protocol):
    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Return one complete model turn for the supplied transcript."""


__all__ = [
    "AssistantMessage",
    "FinalMessage",
    "Message",
    "ModelClient",
    "ModelRequest",
    "ModelResponse",
    "SystemMessage",
    "ToolCall",
    "ToolResultMessage",
    "UserMessage",
]
