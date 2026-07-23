from langgraph.graph import END, START, StateGraph

from app.agentic.answer import AnswerSynthesizer
from app.agentic.critic import AgenticCritic
from app.agentic.nodes import (
    answer_node,
    attempt_finalize_node,
    attempt_reset_node,
    controller_node,
    conversation_answer_node,
    critic_node,
    decision_validate_node,
    evidence_node,
    recovery_node,
    response_node,
    run_finalize_node,
    run_init_node,
    tool_executor_node,
    validate_plan_node,
)
from app.agentic.planning.controller import AgentController
from app.agentic.runtime.clock import (
    Clock,
    SystemClock,
    begin_node_timing,
    end_node_timing,
)
from app.agentic.runtime.guards import (
    BudgetResource,
    apply_runtime_failure,
    runtime_gate_failure,
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
        self.controller = controller
        self.registry = registry
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
        graph.add_node("attempt_finalize", self._attempt_finalize)
        graph.add_node("recovery", self._recovery)
        graph.add_node("attempt_reset", self._attempt_reset)
        graph.add_node("run_finalize", self._run_finalize)
        graph.add_node("response", response_node)

        graph.add_edge(START, "run_init")
        graph.add_edge("run_init", "controller")
        graph.add_conditional_edges(
            "controller",
            _route_after_controller,
            {
                "decision_validate": "decision_validate",
                "response": "attempt_finalize",
            },
        )
        graph.add_conditional_edges(
            "decision_validate",
            _route_after_decision,
            {
                "conversation_answer": "conversation_answer",
                "validate": "validate",
                "response": "attempt_finalize",
            },
        )
        graph.add_edge("conversation_answer", "attempt_finalize")
        graph.add_conditional_edges(
            "validate",
            _route_after_validate,
            {
                "tools": "tools",
                "response": "attempt_finalize",
            },
        )
        graph.add_conditional_edges(
            "tools",
            _route_after_tools,
            {"evidence": "evidence", "response": "attempt_finalize"},
        )
        graph.add_conditional_edges(
            "evidence",
            _route_after_evidence,
            {
                "answer": "answer",
                "response": "attempt_finalize",
            },
        )
        graph.add_conditional_edges(
            "answer",
            _route_after_answer,
            {
                "critic": "critic",
                "response": "attempt_finalize",
            },
        )
        graph.add_edge("critic", "attempt_finalize")
        graph.add_edge("attempt_finalize", "recovery")
        graph.add_conditional_edges(
            "recovery",
            _route_after_recovery,
            {"replan": "attempt_reset", "terminal": "run_finalize"},
        )
        graph.add_conditional_edges(
            "attempt_reset",
            _route_after_attempt_reset,
            {"controller": "controller", "terminal": "run_finalize"},
        )
        graph.add_edge("run_finalize", "response")
        graph.add_edge("response", END)
        return graph.compile()

    async def _controller(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state, resource="controller"):
            return state
        return await self._timed_async(state, controller_node, self.controller)

    def _decision_validate(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state):
            return state
        return self._timed_sync(
            state,
            decision_validate_node,
            self.registry,
        )

    async def _tools(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state):
            return state
        return await self._timed_async(
            state,
            tool_executor_node,
            self.executor,
            self.clock,
        )

    def _validate(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state):
            return state
        return self._timed_sync(
            state,
            validate_plan_node,
            self.registry,
        )

    def _evidence(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state):
            return state
        return self._timed_sync(state, evidence_node, self.registry)

    async def _answer(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state, resource="answer"):
            return state
        return await self._timed_async(state, answer_node, self.answer_synthesizer)

    def _critic(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state):
            return state
        return self._timed_sync(state, critic_node, self.critic)

    def _run_init(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(state, run_init_node, self.runtime_policy, self.clock)

    def _conversation_answer(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state):
            return state
        return self._timed_sync(state, conversation_answer_node)

    def _attempt_finalize(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(state, attempt_finalize_node, self.clock)

    def _recovery(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(state, recovery_node, self.registry, self.clock)

    def _attempt_reset(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(state, attempt_reset_node, self.clock)

    def _run_finalize(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(state, run_finalize_node, self.clock)

    def _guard(
        self,
        state: AgentRunState,
        *,
        resource: BudgetResource | None = None,
    ) -> bool:
        failure = runtime_gate_failure(state, self.clock, resource=resource)
        if failure is None:
            return False
        apply_runtime_failure(state, failure)
        return True

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


def _route_after_recovery(state: AgentRunState) -> str:
    return "replan" if state.recovery_action == "replan" else "terminal"


def _route_after_attempt_reset(state: AgentRunState) -> str:
    if state.recovery_action == "terminal" or state.runtime_failure_code is not None:
        return "terminal"
    return "controller"
