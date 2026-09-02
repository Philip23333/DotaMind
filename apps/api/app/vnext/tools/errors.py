"""Stable, model-visible errors produced by agent-visible tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ToolErrorCode = Literal[
    "unknown_tool",
    "invalid_arguments",
    "provider_error",
    "artifact_error",
    "tool_timeout",
    "tool_execution_error",
    "invalid_tool_output",
    "invalid_source_locator",
    "artifact_not_found",
    "artifact_path_not_found",
    "artifact_type_mismatch",
    "unsupported_resource",
    "unsupported_scope",
    "unsupported_field",
    "invalid_value",
    "configuration_error",
    "provider_timeout",
    "provider_http_error",
    "provider_schema_error",
]


class ToolError(BaseModel):
    """A sanitized, structured failure from a tool invocation."""

    model_config = ConfigDict(extra="forbid")

    code: ToolErrorCode
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


__all__ = ["ToolError", "ToolErrorCode"]
