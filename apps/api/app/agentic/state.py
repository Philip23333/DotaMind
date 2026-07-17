from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agentic.answer import AnswerSynthesisResult
from app.agentic.conversation.models import Turn
from app.agentic.critic import AgenticCriticReview
from app.agentic.evidence import EvidenceGraph
from app.agentic.models import ExecutionPlan, ToolResult
from app.agentic.planning.planner import AgenticPlannerResult

AgentRunStatus = Literal["ok", "insufficient_tools", "error"]


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
    # Set by validate_plan_node so stateful invalid plans receive the same
    # public privacy envelope as planner failures.
    validation_failed: bool = False
    planning: AgenticPlannerResult | None = None
    plan: ExecutionPlan | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)
    evidence_graph: EvidenceGraph | None = None
    answer: AnswerSynthesisResult | None = None
    review: AgenticCriticReview | None = None
    status: AgentRunStatus = "error"
    reason: str = ""
    errors: list[str] = Field(default_factory=list)
    trace: list[AgentTraceEvent] = Field(default_factory=list)
    response_type: str | None = None
    response: dict[str, Any] | None = None

    def add_trace(self, node: str, action: str, status: str) -> None:
        self.trace.append(AgentTraceEvent(node=node, action=action, status=status))
