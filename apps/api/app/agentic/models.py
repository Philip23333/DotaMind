from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ToolResultStatus = Literal["ok", "error"]


class ToolCall(BaseModel):
    id: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)


class ExecutionConstraints(BaseModel):
    max_tool_calls: int = Field(default=6, ge=1, le=20)
    allow_mock: bool = False


class QueryContext(BaseModel):
    """Cross-cutting scope filters shared across all tool calls in a plan.

    Set once at plan level. Tool input_models do not carry these fields;
    handlers receive context as a second argument and apply it internally.
    """

    model_config = ConfigDict(extra="forbid")

    bracket: list[str] | None = None
    # STRATZ-only. Relative count of recent *completed* STRATZ weeks to fetch as
    # per-week buckets (1 week = one STRATZ week, 604800s-aligned). null is
    # resolved by STRATZ handlers to the policy default (1 = latest completed
    # week); the LLM never emits a raw week epoch.
    weeks_back: int | None = Field(default=None, ge=1)
    position_ids: list[str] | None = None
    region_ids: list[str] | None = None
    game_mode_ids: list[str] | None = None


class ExecutionPlan(BaseModel):
    intent: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    output_contract: str = Field(min_length=1)
    context: QueryContext = Field(default_factory=QueryContext)
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
