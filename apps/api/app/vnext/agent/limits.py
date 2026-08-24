"""General, scenario-neutral limits for an agent run."""

from pydantic import BaseModel, ConfigDict, Field


class AgentLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=8, ge=1)
    max_tool_calls: int = Field(default=16, ge=0)
    deadline_seconds: float | None = Field(default=60.0, gt=0)
    default_tool_timeout: float | None = Field(default=30.0, gt=0)


__all__ = ["AgentLimits"]
