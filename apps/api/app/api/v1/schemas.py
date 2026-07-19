from typing import Any, Literal

from pydantic import UUID4, BaseModel, Field

SupportedGame = Literal["dota2"]


class PlanRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    game: SupportedGame = "dota2"
    # Provide a UUID v4 to enable multi-turn session memory.
    # Omit (or pass null) for stateless single-turn mode.
    session_id: UUID4 | None = None


class PlanResponse(BaseModel):
    query: str
    game: SupportedGame
    status: Literal[
        "ok",
        "clarification_required",
        "insufficient_context",
        "insufficient_tools",
        "insufficient_evidence",
        "error",
    ]
    reason: str
    response_type: str | None = None
    error_code: str | None = None
    # Echoed back so clients can continue the conversation.
    session_id: str | None = None
    decision_kind: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    planner_required_evidence: list[str] = Field(default_factory=list)
    effective_required_evidence: list[str] = Field(default_factory=list)
    required_evidence_sources: dict[str, list[str]] = Field(default_factory=dict)
    plan: dict[str, Any] | None = None
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    evidence_graph: dict[str, Any] | None = None
    answer: dict[str, Any] | None = None
    review: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
