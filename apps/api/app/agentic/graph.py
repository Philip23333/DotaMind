from langgraph.graph import END, START, StateGraph

from app.agentic.answer import AnswerSynthesizer
from app.agentic.critic import AgenticCritic
from app.agentic.nodes import (
    answer_node,
    critic_node,
    evidence_node,
    planner_node,
    response_node,
    tool_executor_node,
    validate_plan_node,
)
from app.agentic.planner import AgenticPlanner
from app.agentic.registry import ToolExecutor, ToolRegistry
from app.agentic.state import AgentRunState


class AgentGraphRunner:
    def __init__(self, planner: AgenticPlanner, registry: ToolRegistry) -> None:
        self.planner = planner
        self.registry = registry
        self.executor = ToolExecutor(registry)
        self.answer_synthesizer = AnswerSynthesizer()
        self.critic = AgenticCritic()
        self.graph = self._compile_graph()

    async def run(self, state: AgentRunState) -> AgentRunState:
        result = await self.graph.ainvoke(state)
        return AgentRunState.model_validate(result)

    def _compile_graph(self):
        graph = StateGraph(AgentRunState)
        graph.add_node("planner", self._planner)
        graph.add_node("validate", validate_plan_node)
        graph.add_node("tools", self._tools)
        graph.add_node("evidence", self._evidence)
        graph.add_node("answer", self._answer)
        graph.add_node("critic", self._critic)
        graph.add_node("response", response_node)

        graph.add_edge(START, "planner")
        graph.add_conditional_edges(
            "planner",
            _route_after_planner,
            {
                "validate": "validate",
                "response": "response",
            },
        )
        graph.add_conditional_edges(
            "validate",
            _route_after_validate,
            {
                "tools": "tools",
                "evidence": "evidence",
            },
        )
        graph.add_edge("tools", "evidence")
        graph.add_conditional_edges(
            "evidence",
            _route_after_evidence,
            {
                "answer": "answer",
                "response": "response",
            },
        )
        graph.add_conditional_edges(
            "answer",
            _route_after_answer,
            {
                "critic": "critic",
                "response": "response",
            },
        )
        graph.add_edge("critic", "response")
        graph.add_edge("response", END)
        return graph.compile()

    async def _planner(self, state: AgentRunState) -> AgentRunState:
        return await planner_node(state, self.planner)

    async def _tools(self, state: AgentRunState) -> AgentRunState:
        return await tool_executor_node(state, self.executor)

    def _evidence(self, state: AgentRunState) -> AgentRunState:
        return evidence_node(state, self.registry)

    async def _answer(self, state: AgentRunState) -> AgentRunState:
        return await answer_node(state, self.answer_synthesizer)

    def _critic(self, state: AgentRunState) -> AgentRunState:
        return critic_node(state, self.critic)


def _route_after_planner(state: AgentRunState) -> str:
    if state.status in {"error", "insufficient_tools"}:
        return "response"
    return "validate"


def _route_after_validate(state: AgentRunState) -> str:
    if state.status == "error":
        return "evidence"
    return "tools"


def _route_after_evidence(state: AgentRunState) -> str:
    if state.status == "error":
        return "response"
    return "answer"


def _route_after_answer(state: AgentRunState) -> str:
    if state.status == "error":
        return "response"
    return "critic"
