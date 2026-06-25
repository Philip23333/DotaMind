from app.agentic.answer import AnswerSynthesizer
from app.agentic.critic import AgenticCritic
from app.agentic.planner import AgenticPlanner
from app.agentic.registry import ToolExecutor
from app.agentic.runner import PlanRunner
from app.agentic.state import AgentRunState
from app.agentic.stratz_tools import build_default_tool_registry
from app.core.config import get_settings


class PlanService:
    """Experimental v2.5 LLM planner use case. No fallback to legacy pipeline."""

    def __init__(self, planner: AgenticPlanner | None = None) -> None:
        self.registry = build_default_tool_registry(get_settings())
        self.planner = planner or AgenticPlanner(self.registry)
        self.answer_synthesizer = AnswerSynthesizer()
        self.critic = AgenticCritic()

    async def run(self, query: str, game: str = "dota2") -> AgentRunState:
        state = AgentRunState(query=query, game=game)
        state.add_trace("planner", "create execution plan", "planned")
        planning = await self.planner.plan(query, game)
        state.planning = planning
        state.plan = planning.plan
        state.reason = planning.reason
        if planning.status != "planned" or planning.plan is None:
            state.status = planning.status
            state.errors = planning.errors
            state.add_trace("planner", planning.reason or planning.status, planning.status)
            return state

        state.add_trace("planner", planning.reason or "plan accepted", "completed")
        state.add_trace("runner", "execute planned tool calls", "planned")
        run_result = await PlanRunner(ToolExecutor(self.registry)).run(planning.plan)
        state.plan = run_result.plan
        state.tool_results = run_result.tool_results
        state.evidence_graph = run_result.evidence_graph
        state.errors = run_result.errors
        if run_result.status != "ok":
            state.status = "error"
            state.add_trace("runner", "tool execution failed", "failed")
            return state

        state.add_trace("runner", "tool execution completed", "completed")
        if state.evidence_graph is None:
            state.status = "error"
            state.errors.append("Plan runner did not produce an evidence graph")
            state.add_trace("evidence", "evidence graph missing", "failed")
            return state

        state.add_trace("answer", "synthesize structured answer", "planned")
        state.answer = self.answer_synthesizer.synthesize(run_result.plan, state.evidence_graph)
        state.add_trace("answer", f"answer status: {state.answer.status}", "completed")

        state.add_trace("critic", "review plan evidence and answer", "planned")
        state.review = self.critic.review(run_result.plan, state.evidence_graph, state.answer)
        state.add_trace(
            "critic",
            f"review severity: {state.review.severity}",
            state.review.severity,
        )
        state.status = "ok"
        return state
