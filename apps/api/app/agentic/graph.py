from langgraph.graph import END, START, StateGraph

from app.agentic.answer import AnswerSynthesizer
from app.agentic.critic import AgenticCritic
from app.agentic.nodes import (
    answer_node,
    controller_node,
    conversation_answer_node,
    critic_node,
    decision_validate_node,
    evidence_node,
    response_node,
    tool_executor_node,
    validate_plan_node,
)
from app.agentic.planning.controller import AgentController
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolExecutor, ToolRegistry


class AgentGraphRunner:
    def __init__(self, controller: AgentController, registry: ToolRegistry) -> None:
        self.controller = controller
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
        graph.add_node("controller", self._controller)
        graph.add_node("decision_validate", self._decision_validate)
        graph.add_node("conversation_answer", conversation_answer_node)
        graph.add_node("validate", self._validate)
        graph.add_node("tools", self._tools)
        graph.add_node("evidence", self._evidence)
        graph.add_node("answer", self._answer)
        graph.add_node("critic", self._critic)
        graph.add_node("response", response_node)

        graph.add_edge(START, "controller")
        graph.add_conditional_edges(
            "controller",
            _route_after_controller,
            {
                "decision_validate": "decision_validate",
                "response": "response",
            },
        )
        graph.add_conditional_edges(
            "decision_validate",
            _route_after_decision,
            {
                "conversation_answer": "conversation_answer",
                "validate": "validate",
                "response": "response",
            },
        )
        graph.add_edge("conversation_answer", "response")
        graph.add_conditional_edges(
            "validate",
            _route_after_validate,
            {
                "tools": "tools",
                "response": "response",
            },
        )
        graph.add_conditional_edges(
            "tools",
            _route_after_tools,
            {"evidence": "evidence", "response": "response"},
        )
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

    async def _controller(self, state: AgentRunState) -> AgentRunState:
        return await controller_node(state, self.controller)

    def _decision_validate(self, state: AgentRunState) -> AgentRunState:
        return decision_validate_node(state, self.registry)

    async def _tools(self, state: AgentRunState) -> AgentRunState:
        return await tool_executor_node(state, self.executor)

    def _validate(self, state: AgentRunState) -> AgentRunState:
        return validate_plan_node(state, self.registry)

    def _evidence(self, state: AgentRunState) -> AgentRunState:
        return evidence_node(state, self.registry)

    async def _answer(self, state: AgentRunState) -> AgentRunState:
        return await answer_node(state, self.answer_synthesizer)

    def _critic(self, state: AgentRunState) -> AgentRunState:
        return critic_node(state, self.critic)


def _route_after_controller(state: AgentRunState) -> str:
    if state.status == "error":
        return "response"
    return "decision_validate"


def _route_after_decision(state: AgentRunState) -> str:
    if state.status == "error":
        return "response"
    if state.decision_kind == "direct_answer":
        return "conversation_answer"
    if state.decision_kind == "tool_plan":
        return "validate"
    return "response"


def _route_after_validate(state: AgentRunState) -> str:
    if state.status == "error":
        return "response"
    return "tools"


def _route_after_tools(state: AgentRunState) -> str:
    if state.status == "error":
        return "response"
    return "evidence"


def _route_after_evidence(state: AgentRunState) -> str:
    if state.status == "error":
        return "response"
    return "answer"


def _route_after_answer(state: AgentRunState) -> str:
    if state.status == "error":
        return "response"
    return "critic"
