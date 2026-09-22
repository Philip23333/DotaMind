"""General, scenario-neutral limits for an agent run."""

from pydantic import BaseModel, ConfigDict, Field


class AgentLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=20, ge=1)
    deadline_seconds: float | None = Field(default=120.0, gt=0)
    answer_timeout_seconds: float | None = Field(default=40.0, gt=0)
    degraded_answer_timeout_seconds: float | None = Field(default=15.0, gt=0)
    default_tool_timeout: float | None = Field(default=60.0, gt=0)
    max_materialized_context_bytes: int = Field(default=160 * 1024, ge=1)
    compaction_recent_history_bytes: int = Field(default=32 * 1024, gt=0, strict=True)
    compaction_max_input_bytes: int = Field(default=256 * 1024, gt=0, strict=True)
    compaction_max_output_tokens: int = Field(default=2048, gt=0, strict=True)
    compaction_max_summary_bytes: int = Field(default=8 * 1024, gt=0, strict=True)


__all__ = ["AgentLimits"]
