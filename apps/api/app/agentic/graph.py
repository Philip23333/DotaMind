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
    run_finalize_node,
    run_init_node,
    tool_executor_node,
    validate_plan_node,
)
from app.agentic.planning.contracts import CONTRACT_REGISTRY
from app.agentic.planning.controller import AgentController
from app.agentic.runtime.clock import (
    Clock,
    SystemClock,
    begin_node_timing,
    end_node_timing,
)
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolExecutor, ToolRegistry
from app.core.config import RuntimePolicy


class AgentGraphRunner:
    def __init__(
        self,
        controller: AgentController,
        registry: ToolRegistry,
        runtime_policy: RuntimePolicy | None = None,
        clock: Clock | None = None,
    ) -> None:
        if isinstance(controller, AgentController) and controller.registry is not registry:
            raise ValueError("AgentController and AgentGraphRunner must share a registry")
        self.controller = controller
        self.registry = registry
        self.contract_registry = (
            controller.contract_registry
            if isinstance(controller, AgentController)
            else CONTRACT_REGISTRY
        )
        self.executor = ToolExecutor(registry)
        self.answer_synthesizer = AnswerSynthesizer()
        self.critic = AgenticCritic()
        self.runtime_policy = runtime_policy or RuntimePolicy()
        self.clock = clock or SystemClock()
        self.graph = self._compile_graph()

    async def run(self, state: AgentRunState) -> AgentRunState:
        result = await self.graph.ainvoke(state)
        return AgentRunState.model_validate(result)

    def _compile_graph(self):
        graph = StateGraph(AgentRunState)
        graph.add_node("run_init", self._run_init)
        graph.add_node("controller", self._controller)
        graph.add_node("decision_validate", self._decision_validate)
        graph.add_node("conversation_answer", self._conversation_answer)
        graph.add_node("validate", self._validate)
        graph.add_node("tools", self._tools)
        graph.add_node("evidence", self._evidence)
        graph.add_node("answer", self._answer)
        graph.add_node("critic", self._critic)
        graph.add_node("run_finalize", self._run_finalize)
        graph.add_node("response", response_node)

        graph.add_edge(START, "run_init")
        graph.add_edge("run_init", "controller")
        graph.add_conditional_edges(
            "controller",
            _route_after_controller,
            {
                "decision_validate": "decision_validate",
                "response": "run_finalize",
            },
        )
        graph.add_conditional_edges(
            "decision_validate",
            _route_after_decision,
            {
                "conversation_answer": "conversation_answer",
                "validate": "validate",
                "response": "run_finalize",
            },
        )
        graph.add_edge("conversation_answer", "run_finalize")
        graph.add_conditional_edges(
            "validate",
            _route_after_validate,
            {
                "tools": "tools",
                "response": "run_finalize",
            },
        )
        graph.add_conditional_edges(
            "tools",
            _route_after_tools,
            {"evidence": "evidence", "response": "run_finalize"},
        )
        graph.add_conditional_edges(
            "evidence",
            _route_after_evidence,
            {
                "answer": "answer",
                "response": "run_finalize",
            },
        )
        graph.add_conditional_edges(
            "answer",
            _route_after_answer,
            {
                "critic": "critic",
                "response": "run_finalize",
            },
        )
        graph.add_edge("critic", "run_finalize")
        graph.add_edge("run_finalize", "response")
        graph.add_edge("response", END)
        return graph.compile()

    async def _controller(self, state: AgentRunState) -> AgentRunState:
        return await self._timed_async(state, controller_node, self.controller)

    def _decision_validate(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(
            state,
            decision_validate_node,
            self.registry,
            self.contract_registry,
        )

    async def _tools(self, state: AgentRunState) -> AgentRunState:
        return await self._timed_async(state, tool_executor_node, self.executor)

    def _validate(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(
            state,
            validate_plan_node,
            self.registry,
            self.contract_registry,
        )

    def _evidence(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(state, evidence_node, self.registry)

    async def _answer(self, state: AgentRunState) -> AgentRunState:
        return await self._timed_async(state, answer_node, self.answer_synthesizer)

    def _critic(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(state, critic_node, self.critic)

    def _run_init(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(state, run_init_node, self.runtime_policy, self.clock)

    def _conversation_answer(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(state, conversation_answer_node)

    def _run_finalize(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(state, run_finalize_node, self.clock)

    def _timed_sync(self, state, function, *args):
        token = begin_node_timing(self.clock)
        try:
            return function(state, *args)
        finally:
            end_node_timing(token)

    async def _timed_async(self, state, function, *args):
        token = begin_node_timing(self.clock)
        try:
            return await function(state, *args)
        finally:
            end_node_timing(token)


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
    if (
        state.status == "error"
        or state.evidence_graph is None
        or bool(state.evidence_graph.missing)
    ):
        return "response"
    return "answer"


def _route_after_answer(state: AgentRunState) -> str:
    if (
        state.status == "error"
        or state.answer is None
        or state.answer.status in {"error", "insufficient_evidence"}
    ):
        return "response"
    return "critic"
