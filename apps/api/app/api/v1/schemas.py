from typing import Any, Literal

from pydantic import UUID4, BaseModel, ConfigDict, Field

SupportedGame = Literal["dota2"]
RuntimeStage = Literal[
    "controller",
    "decision_validation",
    "plan_validation",
    "conversation_answer",
    "tool_execution",
    "evidence",
    "answer",
    "critic",
    "execution",
]


class PlanRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    game: SupportedGame = "dota2"
    # Provide a UUID v4 to enable multi-turn session memory.
    # Omit (or pass null) for stateless single-turn mode.
    session_id: UUID4 | None = None


class StrictPublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeBudgetLimits(StrictPublicModel):
    max_replans: int
    max_tool_calls_total: int
    max_controller_calls: int
    max_answer_calls: int
    max_elapsed_seconds: int


class RuntimeBudgetUsed(StrictPublicModel):
    replans_used: int
    tool_calls_used: int
    controller_calls_used: int
    answer_calls_used: int


class RuntimeBudgetSummary(StrictPublicModel):
    limits: RuntimeBudgetLimits
    used: RuntimeBudgetUsed


class RuntimeToolCallStatus(StrictPublicModel):
    tool_call_id: str
    tool: str
    status: Literal["ok", "error"]
    latency_ms: int


class RuntimeEvidenceSummary(StrictPublicModel):
    required_kinds: list[str]
    present_kinds: list[str]
    missing_kinds: list[str]
    completeness: float
    mock_used: bool
    evidence_count: int


class RuntimeAnswerSummary(StrictPublicModel):
    answer_type: str
    status: str
    confidence: float | None


class RuntimeCriticSummary(StrictPublicModel):
    passed: bool
    severity: Literal["pass", "warning", "failed"]
    issue_count: int


class RuntimeAttemptSummary(StrictPublicModel):
    attempt_index: int
    decision_kind: str | None
    status: Literal[
        "ok",
        "clarification_required",
        "insufficient_context",
        "insufficient_tools",
        "insufficient_evidence",
        "error",
    ]
    failure_stage: RuntimeStage | None
    duration_ms: int
    tool_call_statuses: list[RuntimeToolCallStatus]
    evidence_summary: RuntimeEvidenceSummary | None
    answer_summary: RuntimeAnswerSummary | None
    critic_summary: RuntimeCriticSummary | None


class RuntimeSummary(StrictPublicModel):
    run_id: UUID4
    duration_ms: int
    terminal_stage: RuntimeStage
    budget: RuntimeBudgetSummary
    attempts: list[RuntimeAttemptSummary]


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
    runtime: RuntimeSummary
