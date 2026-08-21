import asyncio
import logging

from langgraph.graph import END, START, StateGraph

from app.agentic.answer import AnswerSynthesizer
from app.agentic.conversation.models import (
    ControllerContextExecutionSummary,
    ConversationMessage,
)
from app.agentic.critic import AgenticCritic
from app.agentic.models import ExecutionPlan
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
from app.agentic.runtime.errors import AgentExecutionError, NodeExecutionFailure
from app.agentic.runtime.finalization import build_interrupted_summary
from app.agentic.runtime.guards import (
    BudgetResource,
    apply_runtime_failure,
    runtime_gate_failure,
)
from app.agentic.runtime.models import FailureStage
from app.agentic.runtime.streaming import PhaseStreamEvent, publish_stream_event
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolExecutor, ToolRegistry
from app.core.config import RuntimePolicy, get_policy
from app.observability import emit_event, id_prefix, record_run

logger = logging.getLogger(__name__)


class AgentGraphRunner:
    def __init__(
        self,
        controller: AgentController,
        registry: ToolRegistry,
        runtime_policy: RuntimePolicy | None = None,
        clock: Clock | None = None,
        history_lookup_max_per_run: int | None = None,
    ) -> None:
        self.controller = controller
        self.registry = registry
        self.executor = ToolExecutor(registry)
        self.answer_synthesizer = AnswerSynthesizer()
        self.critic = AgenticCritic()
        self.runtime_policy = runtime_policy or RuntimePolicy()
        self.clock = clock or SystemClock()
        self.history_lookup_max_per_run = (
            history_lookup_max_per_run
            if history_lookup_max_per_run is not None
            else get_policy().conversation.history_lookup_max_per_run
        )
        self.graph = self._compile_graph()

    async def run(self, state: AgentRunState) -> AgentRunState:
        started_monotonic = self.clock.monotonic()
        emit_event(logger, "agent_run_started", status="started")
        try:
            result = await self.graph.ainvoke(state)
        except asyncio.CancelledError:
            duration_ms = self._elapsed_ms(started_monotonic)
            summary = build_interrupted_summary(
                state,
                self.clock,
                failure_code="request_cancelled",
                failure_stage="execution",
                failed_node="graph",
            )
            record_run(
                summary,
                status="cancelled",
                response_type="request_cancelled",
                duration_ms=duration_ms,
            )
            emit_event(
                logger,
                "agent_run_cancelled",
                status="cancelled",
                run_id_prefix=self._run_id_prefix(summary),
                duration_ms=duration_ms,
                failure_stage="execution",
                failure_code="request_cancelled",
            )
            raise
        except NodeExecutionFailure as exc:
            duration_ms = self._elapsed_ms(started_monotonic)
            summary = build_interrupted_summary(
                exc.state,
                self.clock,
                failure_code="execution_error",
                failure_stage=exc.failure_stage,
                failed_node=exc.node,
            )
            self._record_failed_run(summary, exc.node, exc.failure_stage, duration_ms)
            raise AgentExecutionError(exc.failure_stage) from exc
        except Exception as exc:
            duration_ms = self._elapsed_ms(started_monotonic)
            summary = build_interrupted_summary(
                state,
                self.clock,
                failure_code="execution_error",
                failure_stage="execution",
                failed_node="graph",
            )
            self._record_failed_run(summary, "graph", "execution", duration_ms)
            raise AgentExecutionError() from exc
        completed = AgentRunState.model_validate(result)
        duration_ms = self._elapsed_ms(started_monotonic)
        completed.run_duration_ms = duration_ms
        if completed.status == "waiting_input":
            emit_event(
                logger,
                "agent_run_waiting_input",
                status="waiting_input",
                run_id_prefix=self._run_id_prefix(completed),
                duration_ms=duration_ms,
            )
            self._emit_attempts(completed)
            return completed
        if completed.response is not None and isinstance(completed.response.get("runtime"), dict):
            completed.response["runtime"]["duration_ms"] = duration_ms
        record_run(completed, duration_ms=duration_ms)
        emit_event(
            logger,
            "agent_run_completed",
            status=completed.status,
            run_id_prefix=self._run_id_prefix(completed),
            duration_ms=duration_ms,
        )
        self._emit_attempts(completed)
        return completed

    def _record_failed_run(
        self,
        state: AgentRunState,
        node: str,
        failure_stage: FailureStage,
        duration_ms: int,
    ) -> None:
        record_run(
            state,
            status="error",
            response_type="execution_error",
            duration_ms=duration_ms,
        )
        emit_event(
            logger,
            "agent_run_failed",
            status="error",
            run_id_prefix=self._run_id_prefix(state),
            node=node,
            duration_ms=duration_ms,
            failure_stage=failure_stage,
            failure_code="execution_error",
        )
        self._emit_attempts(state)

    def _emit_attempts(self, state: AgentRunState) -> None:
        run_id = self._run_id_prefix(state)
        for attempt in state.attempts:
            emit_event(
                logger,
                "agent_attempt_finalized",
                status=attempt.status,
                run_id_prefix=run_id,
                attempt_index=attempt.attempt_index,
                duration_ms=attempt.duration_ms,
                failure_stage=attempt.failure_stage,
                failure_code=attempt.failure_code,
                recovery_code=attempt.recovery_code,
            )

    def _elapsed_ms(self, started_monotonic: float) -> int:
        return max(0, round((self.clock.monotonic() - started_monotonic) * 1000))

    @staticmethod
    def _run_id_prefix(state: AgentRunState) -> str | None:
        return id_prefix(state.run_context.run_id) if state.run_context is not None else None

    def _compile_graph(self):
        graph = StateGraph(AgentRunState)
        graph.add_node("run_init", self._run_init)
        graph.add_node("checkpoint", self._checkpoint)
        graph.add_node("controller", self._controller)
        graph.add_node("decision_validate", self._decision_validate)
        graph.add_node("conversation_answer", self._conversation_answer)
        graph.add_node("validate", self._validate)
        graph.add_node("tools", self._tools)
        graph.add_node("controller_context", self._controller_context)
        graph.add_node("evidence", self._evidence)
        graph.add_node("answer", self._answer)
        graph.add_node("critic", self._critic)
        graph.add_node("attempt_finalize", self._attempt_finalize)
        graph.add_node("recovery", self._recovery)
        graph.add_node("attempt_reset", self._attempt_reset)
        graph.add_node("run_finalize", self._run_finalize)
        graph.add_node("response", self._response)

        graph.add_edge(START, "run_init")
        graph.add_conditional_edges(
            "run_init",
            _route_after_run_init,
            {"controller": "controller", "tools": "tools"},
        )
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
            self._route_after_tools,
            {
                "controller": "controller",
                "controller_context": "controller_context",
                "evidence": "evidence",
                "checkpoint": "checkpoint",
                "response": "attempt_finalize",
            },
        )
        graph.add_conditional_edges(
            "controller_context",
            _route_after_controller_context,
            {
                "controller": "controller",
                "response": "attempt_finalize",
            },
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
        graph.add_edge("checkpoint", END)
        return graph.compile()

    async def _controller(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state, resource="controller"):
            return state
        publish_stream_event(PhaseStreamEvent(phase="planning", attempt_index=state.attempt_index))
        return await self._timed_async(
            state,
            controller_node,
            self.controller,
            node="controller",
            failure_stage="controller",
        )

    def _decision_validate(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state):
            return state
        return self._timed_sync(
            state,
            decision_validate_node,
            self.registry,
            node="decision_validate",
            failure_stage="decision_validation",
        )

    async def _tools(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state):
            return state
        if (
            state.plan is not None
            and _is_controller_context_plan(state.plan, self.registry)
            and state.controller_context_tool_count + len(state.plan.tool_calls)
            > self.history_lookup_max_per_run
        ):
            state.status = "error"
            state.reason = "conversation context tool limit reached"
            state.errors.append(state.reason)
            return state
        publish_stream_event(
            PhaseStreamEvent(phase="tool_execution", attempt_index=state.attempt_index)
        )
        return await self._timed_async(
            state,
            tool_executor_node,
            self.executor,
            self.clock,
            node="tools",
            failure_stage="tool_execution",
        )

    def _controller_context(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state):
            return state
        return self._timed_sync(
            state,
            _apply_controller_context_results,
            node="controller_context",
            failure_stage="tool_execution",
        )

    def _route_after_tools(self, state: AgentRunState) -> str:
        if state.status == "waiting_input":
            return "checkpoint"
        if state.status == "error":
            return "response"
        if state.plan is not None and _is_controller_context_plan(
            state.plan, self.registry
        ):
            return "controller_context"
        return "evidence"

    def _validate(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state):
            return state
        return self._timed_sync(
            state,
            validate_plan_node,
            self.registry,
            node="validate",
            failure_stage="plan_validation",
        )

    def _evidence(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state):
            return state
        return self._timed_sync(
            state,
            evidence_node,
            self.registry,
            node="evidence",
            failure_stage="evidence",
        )

    async def _answer(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state, resource="answer"):
            return state
        publish_stream_event(PhaseStreamEvent(phase="answering", attempt_index=state.attempt_index))
        return await self._timed_async(
            state,
            answer_node,
            self.answer_synthesizer,
            node="answer",
            failure_stage="answer",
        )

    def _critic(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state):
            return state
        publish_stream_event(PhaseStreamEvent(phase="reviewing", attempt_index=state.attempt_index))
        return self._timed_sync(
            state, critic_node, self.critic, node="critic", failure_stage="critic"
        )

    def _run_init(self, state: AgentRunState) -> AgentRunState:
        if state.resume_node is not None:
            if state.run_context is None or state.run_budget is None:
                raise RuntimeError("checkpoint resume requires initialized run context")
            state.add_trace("run_init", "resume persisted execution", "completed")
            return state
        return self._timed_sync(
            state,
            run_init_node,
            self.runtime_policy,
            self.clock,
            node="run_init",
            failure_stage="execution",
        )

    def _checkpoint(self, state: AgentRunState) -> AgentRunState:
        if state.status != "waiting_input" or state.checkpoint is None:
            raise RuntimeError("checkpoint node requires a waiting Checkpoint")
        state.add_trace("checkpoint", "pause Run for user input", "completed")
        return state

    def _conversation_answer(self, state: AgentRunState) -> AgentRunState:
        if self._guard(state):
            return state
        return self._timed_sync(
            state,
            conversation_answer_node,
            node="conversation_answer",
            failure_stage="conversation_answer",
        )

    def _attempt_finalize(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(
            state,
            attempt_finalize_node,
            self.clock,
            node="attempt_finalize",
            failure_stage="execution",
        )

    def _recovery(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(
            state,
            recovery_node,
            self.registry,
            self.clock,
            node="recovery",
            failure_stage="execution",
        )

    def _attempt_reset(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(
            state,
            attempt_reset_node,
            self.clock,
            node="attempt_reset",
            failure_stage="execution",
        )

    def _run_finalize(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(
            state,
            run_finalize_node,
            self.clock,
            node="run_finalize",
            failure_stage="execution",
        )

    def _response(self, state: AgentRunState) -> AgentRunState:
        return self._timed_sync(
            state, response_node, node="response", failure_stage="execution"
        )

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

    def _timed_sync(
        self,
        state: AgentRunState,
        function,
        *args,
        node: str,
        failure_stage: FailureStage,
    ):
        token = begin_node_timing(self.clock)
        try:
            return function(state, *args)
        except asyncio.CancelledError:
            state.add_trace(
                node,
                "request_cancelled",
                "failed",
                failure_code="request_cancelled",
            )
            raise
        except Exception as exc:
            state.add_trace(
                node,
                "unexpected_failure",
                "failed",
                failure_code="execution_error",
            )
            raise NodeExecutionFailure(state, node, failure_stage) from exc
        finally:
            end_node_timing(token)

    async def _timed_async(
        self,
        state: AgentRunState,
        function,
        *args,
        node: str,
        failure_stage: FailureStage,
    ):
        token = begin_node_timing(self.clock)
        try:
            return await function(state, *args)
        except asyncio.CancelledError:
            state.add_trace(
                node,
                "request_cancelled",
                "failed",
                failure_code="request_cancelled",
            )
            raise
        except Exception as exc:
            state.add_trace(
                node,
                "unexpected_failure",
                "failed",
                failure_code="execution_error",
            )
            raise NodeExecutionFailure(state, node, failure_stage) from exc
        finally:
            end_node_timing(token)


def _route_after_controller(state: AgentRunState) -> str:
    if state.status == "error":
        return "response"
    return "decision_validate"


def _route_after_run_init(state: AgentRunState) -> str:
    return state.resume_node or "controller"


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


def _is_controller_context_plan(
    plan: ExecutionPlan,
    registry: ToolRegistry,
) -> bool:
    if not plan.tool_calls:
        return False
    try:
        return all(
            registry.get(call.tool).result_destination == "controller_context"
            for call in plan.tool_calls
        )
    except KeyError:
        return False


def _apply_controller_context_results(state: AgentRunState) -> AgentRunState:
    retrieved: list[ConversationMessage] = []
    summaries: list[ControllerContextExecutionSummary] = []
    try:
        for result in state.tool_results:
            data = result.data if isinstance(result.data, dict) else {}
            result_messages = [
                ConversationMessage.model_validate(message)
                for message in data.get("messages", [])
            ]
            retrieved.extend(result_messages)
            summaries.append(
                ControllerContextExecutionSummary(
                    tool=result.tool,
                    matched_turns=len(
                        {message.turn_index for message in result_messages}
                    ),
                )
            )
        messages_by_key = {
            (message.turn_index, message.role): message
            for message in state.retrieved_messages
        }
        messages_by_key.update(
            {(message.turn_index, message.role): message for message in retrieved}
        )
        role_order = {"user": 0, "assistant": 1}
        state.retrieved_messages = sorted(
            messages_by_key.values(),
            key=lambda message: (message.turn_index, role_order[message.role]),
        )
    except Exception:
        state.status = "error"
        state.reason = "controller context tool returned invalid messages"
        state.errors.append(state.reason)
        return state
    state.controller_context_summaries.extend(summaries)
    state.controller_context_tool_count += len(summaries)
    state.status = "ok"
    state.reason = ""
    state.errors.clear()
    state.controller_result = None
    state.decision = None
    state.decision_kind = None
    state.plan = None
    state.validation_failed = False
    state.safe_failure_required = False
    state.tool_results.clear()
    state.tool_dispatch_records.clear()
    state.evidence_graph = None
    state.answer = None
    return state


def _route_after_controller_context(state: AgentRunState) -> str:
    return "response" if state.status == "error" else "controller"


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
