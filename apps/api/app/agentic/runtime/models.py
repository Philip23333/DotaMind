from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agentic.models import ToolResult

AgentRunStatus = Literal[
    "ok",
    "clarification_required",
    "insufficient_context",
    "insufficient_tools",
    "insufficient_evidence",
    "error",
]
AttemptStatus = AgentRunStatus
RecoveryCode = Literal["missing_evidence"]
RecoveryAction = Literal["replan", "terminal"]
RuntimeFailureCode = Literal["execution_budget_error", "execution_timeout"]
TerminalStage = Literal[
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
FailureStage = Literal[
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
ToolDispatchStage = Literal[
    "reference_resolution",
    "pre_dispatch",
    "handler",
    "cache_reuse",
]
ToolErrorCode = Literal[
    "reference_resolution_error",
    "tool_not_registered",
    "input_validation_error",
    "handler_error",
]


class StrictRuntimeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunContext(StrictRuntimeModel):
    run_id: UUID
    request_id: UUID | None = None
    session_id: UUID | None = None
    started_at: datetime
    deadline_at: datetime
    prompt_versions: dict[str, str] = Field(default_factory=dict)

    @field_validator("run_id")
    @classmethod
    def require_uuid4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("run_id must be UUID v4")
        return value

    @field_validator("started_at", "deadline_at")
    @classmethod
    def require_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("runtime timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_deadline(self) -> "RunContext":
        if self.deadline_at < self.started_at:
            raise ValueError("deadline_at cannot precede started_at")
        return self


class RunBudget(StrictRuntimeModel):
    max_replans: int = Field(default=1, ge=1)
    max_tool_calls_total: int = Field(default=8, ge=1)
    max_controller_calls: int = Field(default=2, ge=1)
    max_answer_calls: int = Field(default=2, ge=1)
    max_elapsed_seconds: int = Field(default=60, ge=1)
    replans_used: int = Field(default=0, ge=0)
    tool_calls_used: int = Field(default=0, ge=0)
    controller_calls_used: int = Field(default=0, ge=0)
    answer_calls_used: int = Field(default=0, ge=0)

    @field_validator("max_replans")
    @classmethod
    def require_one_replan(cls, value: int) -> int:
        if value != 1:
            raise ValueError("max_replans must equal 1")
        return value

    def record_controller_call(self) -> None:
        self.controller_calls_used += 1

    def record_tool_call(self) -> None:
        self.tool_calls_used += 1

    def record_answer_call(self) -> None:
        self.answer_calls_used += 1

    def record_replan(self) -> None:
        self.replans_used += 1

    def remaining(self, resource: Literal["replans", "tools", "controller", "answer"]) -> int:
        limits = {
            "replans": self.max_replans,
            "tools": self.max_tool_calls_total,
            "controller": self.max_controller_calls,
            "answer": self.max_answer_calls,
        }
        used = {
            "replans": self.replans_used,
            "tools": self.tool_calls_used,
            "controller": self.controller_calls_used,
            "answer": self.answer_calls_used,
        }
        return max(0, limits[resource] - used[resource])

    def exhausted(self, resource: Literal["replans", "tools", "controller", "answer"]) -> bool:
        return self.remaining(resource) == 0

    def deadline_exceeded(self, elapsed_seconds: float) -> bool:
        return elapsed_seconds >= self.max_elapsed_seconds


class ToolDispatchRecord(StrictRuntimeModel):
    tool_call_id: str
    tool: str
    handler_entered: bool
    stage: ToolDispatchStage
    error_code: ToolErrorCode | None = None


class RecoveryExecutedCall(StrictRuntimeModel):
    id: str
    tool: str
    status: Literal["ok"] = "ok"


class RecoveryFeedback(StrictRuntimeModel):
    code: RecoveryCode = "missing_evidence"
    failure_stage: Literal["evidence"] = "evidence"
    missing_evidence: list[str] = Field(min_length=1)
    executed_calls: list[RecoveryExecutedCall] = Field(default_factory=list)
    remaining_tool_budget: int = Field(ge=0)
    replan_index: Literal[1] = 1


class CachedToolCall(StrictRuntimeModel):
    call_id: str
    result: ToolResult
    dispatch: ToolDispatchRecord


class AttemptPlanSummary(StrictRuntimeModel):
    output_contract: str
    tool_call_count: int = Field(ge=0)
    effective_required_evidence: list[str] = Field(default_factory=list)


class AttemptToolCallSummary(StrictRuntimeModel):
    tool_call_id: str
    tool: str
    status: Literal["ok", "error"]
    latency_ms: int = Field(ge=0)
    handler_entered: bool
    dispatch_stage: ToolDispatchStage
    error_code: ToolErrorCode | None = None
    reused: bool = False


class AttemptEvidenceSummary(StrictRuntimeModel):
    required_kinds: list[str] = Field(default_factory=list)
    present_kinds: list[str] = Field(default_factory=list)
    missing_kinds: list[str] = Field(default_factory=list)
    completeness: float = Field(ge=0, le=1)
    mock_used: bool
    evidence_count: int = Field(ge=0)


class AttemptAnswerSummary(StrictRuntimeModel):
    answer_type: str
    status: str
    confidence: float | None = Field(default=None, ge=0, le=1)


class AttemptCriticSummary(StrictRuntimeModel):
    passed: bool
    severity: Literal["pass", "warning", "failed"]
    issue_count: int = Field(ge=0)


class AttemptRecord(StrictRuntimeModel):
    attempt_index: int = Field(ge=0)
    decision_kind: str | None = None
    plan_summary: AttemptPlanSummary | None = None
    tool_calls: list[AttemptToolCallSummary] = Field(default_factory=list)
    evidence_summary: AttemptEvidenceSummary | None = None
    answer_summary: AttemptAnswerSummary | None = None
    critic_summary: AttemptCriticSummary | None = None
    status: AttemptStatus
    failure_stage: FailureStage | None = None
    recovery_code: RecoveryCode | None = None
    started_at: datetime
    duration_ms: int = Field(ge=0)

    @field_validator("started_at")
    @classmethod
    def require_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("attempt started_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class TerminalOutcome(StrictRuntimeModel):
    public_status: AgentRunStatus
    response_type: str
    stable_reason: str
    attempt_status: AttemptStatus
    terminal_stage: TerminalStage
    failure_stage: FailureStage | None = None
