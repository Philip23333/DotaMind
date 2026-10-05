"""Provider-neutral messages exchanged by the vNext runtime and model client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.vnext.tools.errors import ToolError, ToolErrorCode


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


class RawToolCall(_Message):
    """A provider tool call retained before execution eligibility is decided."""

    index: int = Field(ge=0, strict=True)
    id: str = Field(min_length=1, strict=True)
    name: str = Field(min_length=1, strict=True)
    provider_name: str = Field(min_length=1, strict=True)
    raw_arguments: str = Field(strict=True)


class ToolArgumentFailure(_Message):
    """Bounded parse location and category for one rejected argument value."""

    call_index: int = Field(ge=0, strict=True)
    kind: Literal["invalid_json", "non_object_json"]
    message: str = Field(min_length=1)
    position: int | None = Field(default=None, ge=0, strict=True)
    line: int | None = Field(default=None, ge=1, strict=True)
    column: int | None = Field(default=None, ge=1, strict=True)


class RejectedToolCallBatch(_Message):
    """Complete raw tool-call batch rejected before any call can execute."""

    reason: Literal["invalid_tool_arguments", "tool_response_truncated"]
    content: str | None = None
    calls: list[RawToolCall] = Field(min_length=1)
    argument_failures: list[ToolArgumentFailure] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)


class AssistantMessage(_Message):
    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class RejectedAssistantMessage(_Message):
    """A rejected provider batch retained as non-executable conversation history."""

    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[RawToolCall] = Field(min_length=1)


class ToolResultMessage(_Message):
    role: Literal["tool"] = "tool"
    tool_call_id: str = Field(min_length=1)
    content: Any = None
    status: Literal["ok", "error"] = "ok"
    error: ToolError | None = None
    executed: bool | None = Field(default=None, exclude_if=lambda value: value is None)

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


Message = (
    SystemMessage
    | UserMessage
    | RejectedAssistantMessage
    | AssistantMessage
    | ToolResultMessage
    | FinalMessage
)


class ModelTool(_Message):
    """Provider-neutral description of one agent-visible tool."""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]


class ModelRequest(_Message):
    messages: list[Message]
    tools: list[ModelTool] = Field(default_factory=list)
    step: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    max_output_tokens: int | None = Field(
        default=None,
        strict=True,
        gt=0,
        description=(
            "Request-level generated-token limit using provider semantics; "
            "not a UTF-8 byte limit for a compaction summary."
        ),
    )


class ModelResponse(_Message):
    """One provider-neutral model turn with one canonical message."""

    message: AssistantMessage | FinalMessage
    finish_reason: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_final(self) -> bool:
        return isinstance(self.message, FinalMessage)

    @classmethod
    def from_final(cls, content: str, **kwargs: Any) -> ModelResponse:
        return cls(message=FinalMessage(content=content), **kwargs)

    @classmethod
    def from_assistant(cls, message: AssistantMessage, **kwargs: Any) -> ModelResponse:
        return cls(message=message, **kwargs)


@runtime_checkable
class ModelClient(Protocol):
    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Return one complete model turn for the supplied transcript."""


class ModelTextDelta(_Message):
    """A provider-neutral fragment of assistant text emitted while streaming."""

    text: str

    @property
    def delta(self) -> str:
        """A concise alias for consumers that call the fragment a delta."""

        return self.text


@runtime_checkable
class StreamingModelClient(Protocol):
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelTextDelta | ModelResponse]:
        """Yield text fragments followed by exactly one terminal model response."""


__all__ = [
    "AssistantMessage",
    "FinalMessage",
    "Message",
    "ModelClient",
    "ModelRequest",
    "ModelResponse",
    "ModelTextDelta",
    "ModelTool",
    "RawToolCall",
    "RejectedAssistantMessage",
    "RejectedToolCallBatch",
    "SystemMessage",
    "StreamingModelClient",
    "ToolArgumentFailure",
    "ToolError",
    "ToolErrorCode",
    "ToolCall",
    "ToolResultMessage",
    "UserMessage",
]
