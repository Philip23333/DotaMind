"""Strict configuration for durable-history bootstrap and session locators."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class SessionContextLimits(BaseModel):
    """Immutable limits for initial history loading and Artifact locator hints."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    history_bootstrap_max_turns: StrictInt = Field(default=12, gt=0)
    history_bootstrap_max_chars: StrictInt = Field(default=40_000, gt=0)
    artifact_locator_capacity: StrictInt = Field(default=16, gt=0)
    artifact_locator_hint_chars: StrictInt = Field(default=256, gt=0)


__all__ = ["SessionContextLimits"]
