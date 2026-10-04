"""General, scenario-neutral limits for an agent run."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deadline_seconds: float | None = Field(default=300.0, gt=0)
    answer_timeout_seconds: float | None = Field(default=60.0, gt=0)
    default_tool_timeout: float | None = Field(default=60.0, gt=0)
    compaction_keep_recent_tokens: int = Field(default=20_000, gt=0, strict=True)
    compaction_max_input_bytes: int = Field(default=256 * 1024, gt=0, strict=True)
    compaction_reserve_tokens: int = Field(default=16384, ge=2, strict=True)
    compaction_model_max_output_tokens: int | None = Field(default=None, gt=0, strict=True)
    compaction_max_retries: int = Field(default=1, ge=0, le=3, strict=True)
    context_window_tokens: int | None = Field(default=None, gt=0, strict=True)
    model_max_output_tokens: int | None = Field(default=None, gt=0, strict=True)
    application_max_output_tokens: int | None = Field(default=None, gt=0, strict=True)
    context_safety_margin_tokens: int = Field(default=1024, gt=0, strict=True)
    context_estimate_bytes_per_token: int = Field(default=2, gt=0, strict=True)
    context_compaction_test_trigger_percent: int | None = Field(
        default=None,
        ge=1,
        le=99,
        strict=True,
    )

    @model_validator(mode="after")
    def _validate_context_reserve(self) -> "AgentLimits":
        if (
            self.context_window_tokens is not None
            and self.context_safety_margin_tokens >= self.context_window_tokens
        ):
            raise ValueError("context safety margin must be smaller than the context window")
        if (
            self.context_window_tokens is not None
            and self.compaction_reserve_tokens >= self.context_window_tokens
        ):
            raise ValueError("compaction reserve must be smaller than the context window")
        return self


__all__ = ["AgentLimits"]
