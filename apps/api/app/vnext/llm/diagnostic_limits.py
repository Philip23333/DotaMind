"""Validated per-model-client limits for failure diagnostic copies."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelDiagnosticLimits(BaseModel):
    """Byte and item budgets for diagnostic evidence, not model tool calls."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_tool_calls: int = Field(default=64, gt=0, strict=True)
    argument_max_bytes: int = Field(default=64 * 1024, gt=0, strict=True)
    total_argument_max_bytes: int = Field(default=256 * 1024, gt=0, strict=True)
    argument_edge_bytes: int = Field(default=4 * 1024, gt=0, strict=True)

    @model_validator(mode="after")
    def _validate_argument_budgets(self) -> ModelDiagnosticLimits:
        if self.argument_max_bytes > self.total_argument_max_bytes:
            raise ValueError("argument_max_bytes must not exceed total_argument_max_bytes")
        if self.argument_edge_bytes * 2 > self.argument_max_bytes:
            raise ValueError("two argument edges must fit within argument_max_bytes")
        return self


DEFAULT_MODEL_DIAGNOSTIC_LIMITS = ModelDiagnosticLimits()


__all__ = ["DEFAULT_MODEL_DIAGNOSTIC_LIMITS", "ModelDiagnosticLimits"]
