from typing import Any, Literal

from pydantic import BaseModel, Field

ToolResultStatus = Literal["ok", "error"]


class ToolCall(BaseModel):
    id: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)


class ExecutionConstraints(BaseModel):
    max_tool_calls: int = Field(default=6, ge=1, le=20)
    allow_mock: bool = False


class ExecutionPlan(BaseModel):
    intent: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    output_contract: str = Field(min_length=1)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    constraints: ExecutionConstraints = Field(default_factory=ExecutionConstraints)


class ToolSource(BaseModel):
    name: str
    kind: str
    url: str | None = None
    status: str = "live"


class ToolResult(BaseModel):
    tool_call_id: str
    tool: str
    status: ToolResultStatus
    data: Any = None
    source: ToolSource | None = None
    latency_ms: int
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
