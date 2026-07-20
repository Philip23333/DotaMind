from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.agentic.answer import AnswerSynthesisResult
from app.agentic.conversation.models import Turn
from app.agentic.critic import AgenticCriticReview
from app.agentic.evidence import EvidenceGraph
from app.agentic.models import ExecutionPlan, ToolResult
from app.agentic.planning.controller import AgentControllerResult
from app.agentic.planning.decisions import ControllerDecision, ConversationAnswerResult
from app.agentic.runtime.clock import current_node_timing
from app.agentic.runtime.models import (
    AgentRunStatus,
    AttemptRecord,
    FailureStage,
    RunBudget,
    RunContext,
    TerminalStage,
    ToolDispatchRecord,
)

TraceEventStatus = Literal["planned", "completed", "failed"]


class AgentTraceEvent(BaseModel):
    run_id: UUID | None = None
    attempt_index: int = 0
    node: str
    action: str
    status: TraceEventStatus
    started_at: datetime | None = None
    duration_ms: int = 0


class AgentRunState(BaseModel):
    query: str
    game: str
    history: list[Turn] = Field(default_factory=list)
    session_memory_enabled: bool = False
    internal_session_id: UUID | None = None

    run_context: RunContext | None = None
    run_budget: RunBudget | None = None
    run_started_monotonic: float | None = None
    attempt_index: int = 0
    attempt_started_at: datetime | None = None
    attempt_started_monotonic: float | None = None
    attempts: list[AttemptRecord] = Field(default_factory=list)
    attempt_failure_stage: FailureStage | None = None
    terminal_stage: TerminalStage | None = None
    run_duration_ms: int | None = None

    validation_failed: bool = False
    safe_failure_required: bool = False
    controller_result: AgentControllerResult | None = None
    decision: ControllerDecision | None = None
    decision_kind: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    plan: ExecutionPlan | None = None
    planner_required_evidence: list[str] = Field(default_factory=list)
    global_required_evidence: list[str] = Field(default_factory=list)
    effective_required_evidence: list[str] = Field(default_factory=list)
    required_evidence_sources: dict[str, list[str]] = Field(default_factory=dict)
    mandatory_evidence_by_call: dict[str, list[str]] = Field(default_factory=dict)
    tool_results: list[ToolResult] = Field(default_factory=list)
    tool_dispatch_records: list[ToolDispatchRecord] = Field(default_factory=list)
    evidence_graph: EvidenceGraph | None = None
    answer: AnswerSynthesisResult | ConversationAnswerResult | None = None
    review: AgenticCriticReview | None = None
    status: AgentRunStatus = "error"
    reason: str = ""
    errors: list[str] = Field(default_factory=list)
    trace: list[AgentTraceEvent] = Field(default_factory=list)
    response_type: str | None = None
    response: dict[str, Any] | None = None

    def add_trace(self, node: str, action: str, status: TraceEventStatus) -> None:
        timing = current_node_timing()
        started_at = self.run_context.started_at if self.run_context else None
        duration_ms = 0
        if timing is not None:
            started_at = timing.started_at
            if status != "planned":
                duration_ms = max(
                    0,
                    round((timing.clock.monotonic() - timing.started_monotonic) * 1000),
                )
        self.trace.append(
            AgentTraceEvent(
                run_id=self.run_context.run_id if self.run_context else None,
                attempt_index=self.attempt_index,
                node=node,
                action=action,
                status=status,
                started_at=started_at,
                duration_ms=duration_ms,
            )
        )
