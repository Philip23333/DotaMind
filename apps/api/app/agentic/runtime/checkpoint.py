"""Persistent pause and resume contracts for dynamic Agent Graph execution."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agentic.models import ExecutionPlan, ToolResult
from app.agentic.runtime.models import (
    AttemptRecord,
    CachedToolCall,
    RunBudget,
    ToolDispatchRecord,
)


class CheckpointOption(BaseModel):
    """One server-defined choice exposed by a persisted checkpoint."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: dict[str, Any]


class Checkpoint(BaseModel):
    """User interaction required before the current Run can continue."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_type: str = Field(min_length=1)
    question: str = Field(min_length=1)
    options: list[CheckpointOption] = Field(min_length=1)
    source_tool_call_id: str = Field(min_length=1)
    resume_node: Literal["controller", "tools"]


class CheckpointSnapshot(BaseModel):
    """Minimal Agent state needed to resume one paused Run.

    Request history, prompts, raw model output and Answer content deliberately
    do not belong in this durable snapshot.
    """

    model_config = ConfigDict(extra="forbid")

    checkpoint: Checkpoint
    plan: ExecutionPlan
    tool_results: list[ToolResult] = Field(default_factory=list)
    tool_dispatch_records: list[ToolDispatchRecord] = Field(default_factory=list)
    run_budget: RunBudget
    attempt_index: int = Field(ge=0)
    attempts: list[AttemptRecord] = Field(default_factory=list)
    executed_call_fingerprints: dict[str, CachedToolCall] = Field(default_factory=dict)
    selected_option_id: str | None = None
    planner_required_evidence: list[str] = Field(default_factory=list)
    global_required_evidence: list[str] = Field(default_factory=list)
    effective_required_evidence: list[str] = Field(default_factory=list)
    required_evidence_sources: dict[str, list[str]] = Field(default_factory=dict)
    mandatory_evidence_by_call: dict[str, list[str]] = Field(default_factory=dict)


__all__ = ["Checkpoint", "CheckpointOption", "CheckpointSnapshot"]
