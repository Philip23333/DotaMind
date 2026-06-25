from typing import Literal

from pydantic import BaseModel, Field

from app.agentic.answer import AnswerSynthesisResult
from app.agentic.critic import AgenticCriticReview
from app.agentic.evidence import EvidenceGraph
from app.agentic.models import ExecutionPlan, ToolResult
from app.agentic.planner import AgenticPlannerResult

AgentRunStatus = Literal["ok", "insufficient_tools", "error"]


class AgentTraceEvent(BaseModel):
    node: str
    action: str
    status: str


class AgentRunState(BaseModel):
    query: str
    game: str
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

    def add_trace(self, node: str, action: str, status: str) -> None:
        self.trace.append(AgentTraceEvent(node=node, action=action, status=status))
