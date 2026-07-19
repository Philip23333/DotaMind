"""Conversation history data models.

Intentionally free of imports from the rest of the agentic pipeline so this
module can be used by both the agentic layer (summary extraction) and the
application layer (session store / service) without circular dependencies.
These models are also the unit of Redis serialisation in Phase 2.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ResolvedEntity(BaseModel):
    """A named game entity resolved during a turn."""

    type: Literal["hero", "team", "player"]
    name: str
    id: int | str | None = None


class Turn(BaseModel):
    """Compact summary of one completed planning turn.

    Stored in the session history and rendered into the Controller prompt as
    *untrusted context data*, not as instructions or evidence.
    """

    # Monotonic index assigned by SessionStore.append(); placeholder 0 before
    # storage.
    turn_index: int = 0
    # Raw user query, truncated to turn_query_max_chars at extraction time.
    query: str
    # Mirrors AgentRunState.status so downstream renderers can warn on errors.
    status: Literal[
        "ok",
        "clarification_required",
        "insufficient_context",
        "insufficient_tools",
        "insufficient_evidence",
        "error",
    ] = "ok"
    # Mirrors AgentRunState.response_type.
    response_type: str | None = None
    # Semantic intent from the decision; never used as a routing key.
    intent: str | None = None
    # Game entities resolved during the turn (hero/team/player).
    resolved_entities: list[ResolvedEntity] = Field(default_factory=list)
    # Cross-cutting scope filters from ExecutionPlan.context, JSON-safe dict.
    context_scope: dict[str, Any] = Field(default_factory=dict)
    # Minimal continuation state for a clarification turn.
    missing_fields: list[str] = Field(default_factory=list)
    # Human-readable answer summary (truncated) or state.reason on failure.
    response_summary: str = ""
