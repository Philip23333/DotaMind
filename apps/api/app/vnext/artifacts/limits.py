"""Validated budgets for tool-result Artifacts and model observations."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArtifactLimits(BaseModel):
    """Per-runtime byte bounds and per-call Artifact query work limits."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inline_max_bytes: int = Field(default=12 * 1024, gt=0, strict=True)
    observation_max_bytes: int = Field(default=35 * 1024, gt=0, strict=True)
    query_max_work: int = Field(default=100_000, gt=0, strict=True)

    @model_validator(mode="after")
    def _validate_order(self) -> ArtifactLimits:
        if self.inline_max_bytes > self.observation_max_bytes:
            raise ValueError("inline_max_bytes must not exceed observation_max_bytes")
        return self


DEFAULT_ARTIFACT_LIMITS = ArtifactLimits()


__all__ = ["ArtifactLimits", "DEFAULT_ARTIFACT_LIMITS"]
