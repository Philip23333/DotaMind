from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agentic.answer import AnswerSynthesisResult
from app.agentic.conversation.models import Turn
from app.agentic.critic import AgenticCriticReview
from app.agentic.evidence import EvidenceGraph
from app.agentic.models import ExecutionPlan, ToolResult
from app.agentic.planning.controller import AgentControllerResult
from app.agentic.planning.decisions import (
    ControllerDecision,
    ConversationAnswerResult,
)

AgentRunStatus = Literal[
    "ok",
    "clarification_required",
    "insufficient_context",
    "insufficient_tools",
    "insufficient_evidence",
    "error",
]


class AgentTraceEvent(BaseModel):
    node: str
    action: str
    status: str


class AgentRunState(BaseModel):
    query: str
    game: str
    # Conversation history injected by PlanService before graph execution.
    # Not returned to the client; excluded from response_node's model_dump.
    history: list[Turn] = Field(default_factory=list)
    # True for every request that supplied a session_id, including its first turn.
    # response_node uses this to apply the stateful privacy boundary.
    session_memory_enabled: bool = False
    # Invalid controller/plan outputs use a stable public envelope and a
    # redacted persisted failure Turn.
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
    evidence_graph: EvidenceGraph | None = None
    answer: AnswerSynthesisResult | ConversationAnswerResult | None = None
    review: AgenticCriticReview | None = None
    status: AgentRunStatus = "error"
    reason: str = ""
    errors: list[str] = Field(default_factory=list)
    trace: list[AgentTraceEvent] = Field(default_factory=list)
    response_type: str | None = None
    response: dict[str, Any] | None = None

    def add_trace(self, node: str, action: str, status: str) -> None:
        self.trace.append(AgentTraceEvent(node=node, action=action, status=status))
