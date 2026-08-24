"""Stable failures for the vNext runtime and structured tool errors."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ToolErrorCode = Literal[
    "unknown_tool",
    "invalid_arguments",
    "tool_timeout",
    "tool_execution_error",
    "invalid_tool_output",
]


class ToolError(BaseModel):
    """A model-visible, structured failure from a tool invocation."""

    model_config = ConfigDict(extra="forbid")

    code: ToolErrorCode
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class AgentRuntimeError(RuntimeError):
    """Base class for failures that terminate an agent run."""

    code = "agent_runtime_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AgentCancelledError(AgentRuntimeError):
    code = "agent_cancelled"

    def __init__(self, message: str = "agent run was cancelled") -> None:
        super().__init__(message)


class AgentDeadlineExceeded(AgentRuntimeError):
    code = "deadline_exceeded"

    def __init__(self, message: str = "agent run deadline exceeded") -> None:
        super().__init__(message)


class MaxStepsExceeded(AgentRuntimeError):
    code = "max_steps_exceeded"

    def __init__(self, max_steps: int) -> None:
        super().__init__(
            f"agent run exceeded the maximum number of steps ({max_steps})",
            details={"max_steps": max_steps},
        )


class MaxToolCallsExceeded(AgentRuntimeError):
    code = "max_tool_calls_exceeded"

    def __init__(self, max_tool_calls: int, requested: int, used: int) -> None:
        super().__init__(
            f"agent run exceeded the maximum number of tool calls ({max_tool_calls})",
            details={
                "max_tool_calls": max_tool_calls,
                "requested": requested,
                "used": used,
            },
        )


class ModelProviderError(AgentRuntimeError):
    code = "model_provider_error"

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        details = {"exception_type": type(cause).__name__} if cause else {}
        super().__init__(message, details=details)
        self.cause = cause


class ModelProtocolError(AgentRuntimeError):
    code = "model_protocol_error"


# The shorter aliases are useful to callers that want to name failures without
# the implementation-oriented ``Error`` suffix.  The event named
# ``AgentCancelled`` intentionally lives in events.py and is not aliased here.
AgentCancelled = AgentCancelledError
AgentDeadlineExceededError = AgentDeadlineExceeded
MaxStepsExceededError = MaxStepsExceeded
MaxToolCallsExceededError = MaxToolCallsExceeded

__all__ = [
    "AgentCancelled",
    "AgentCancelledError",
    "AgentDeadlineExceeded",
    "AgentDeadlineExceededError",
    "AgentRuntimeError",
    "MaxStepsExceeded",
    "MaxStepsExceededError",
    "MaxToolCallsExceeded",
    "MaxToolCallsExceededError",
    "ModelProviderError",
    "ModelProtocolError",
    "ToolError",
    "ToolErrorCode",
]
