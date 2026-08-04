import logging

from app.agentic.planning.decisions import ToolPlanDecision
from app.agentic.runtime.clock import Clock
from app.agentic.runtime.guards import apply_runtime_failure, runtime_gate_failure
from app.agentic.runtime.recovery import (
    build_recovery_feedback,
    minimum_recovery_tool_calls,
    recoverable_missing_evidence,
)
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolRegistry
from app.observability import emit_event, record_recovery

logger = logging.getLogger(__name__)


def recovery_node(
    state: AgentRunState,
    registry: ToolRegistry,
    clock: Clock,
) -> AgentRunState:
    state.add_trace("recovery", "evaluate bounded recovery", "planned")
    state.recovery_action = "terminal"

    graph = state.evidence_graph
    if graph is None or not graph.missing:
        state.add_trace("recovery", "recovery not applicable", "completed")
        return state

    emit_event(
        logger,
        "recovery_started",
        status="started",
        attempt_index=state.attempt_index,
        recovery_code="missing_evidence",
    )

    gate_failure = runtime_gate_failure(state, clock)
    if gate_failure is not None:
        record_recovery("exhausted", "missing_evidence")
        emit_event(
            logger,
            "recovery_exhausted",
            status="error",
            attempt_index=state.attempt_index,
            failure_code=gate_failure,
            recovery_code="missing_evidence",
        )
        apply_runtime_failure(state, gate_failure)
        state.add_trace("recovery", state.reason, "failed")
        return state

    if state.attempt_index == 1:
        record_recovery("exhausted", "missing_evidence")
        emit_event(
            logger,
            "recovery_exhausted",
            status="completed",
            attempt_index=state.attempt_index,
            recovery_code="missing_evidence",
        )
        state.status = "insufficient_evidence"
        state.response_type = "replan_exhausted"
        state.reason = "replan exhausted"
        state.add_trace("recovery", "replan exhausted", "completed")
        return state

    missing = recoverable_missing_evidence(state, registry)
    if missing is None:
        record_recovery("exhausted", "missing_evidence")
        emit_event(
            logger,
            "recovery_exhausted",
            status="completed",
            attempt_index=state.attempt_index,
            recovery_code="missing_evidence",
        )
        state.add_trace("recovery", "missing evidence is not recoverable", "completed")
        return state

    if state.run_budget is None:
        raise RuntimeError("recovery requires run budget")
    required_tool_calls = minimum_recovery_tool_calls(state, registry, missing)
    if required_tool_calls is None:
        raise RuntimeError("recoverable evidence has no producer cover")
    plan_tool_capacity = state.plan.constraints.max_tool_calls - len(
        state.plan.tool_calls
    )
    available_tool_capacity = min(
        state.run_budget.remaining("tools"),
        max(0, plan_tool_capacity),
    )
    if any(
        state.run_budget.exhausted(resource)
        for resource in ("replans", "controller", "tools")
    ) or available_tool_capacity < required_tool_calls:
        record_recovery("exhausted", "missing_evidence")
        emit_event(
            logger,
            "recovery_exhausted",
            status="completed",
            attempt_index=state.attempt_index,
            recovery_code="missing_evidence",
        )
        state.status = "insufficient_evidence"
        state.response_type = "replan_exhausted"
        state.reason = "replan exhausted"
        state.add_trace("recovery", "replan budget exhausted", "completed")
        return state

    if not isinstance(state.decision, ToolPlanDecision):
        raise RuntimeError("missing-evidence recovery requires a tool plan decision")
    state.recovery_feedback = build_recovery_feedback(
        state,
        missing,
        remaining_tool_budget=available_tool_capacity,
    )
    state.recovery_baseline_decision = state.decision.model_copy(deep=True)
    state.run_budget.record_replan()
    state.recovery_action = "replan"
    record_recovery("completed", "missing_evidence")
    emit_event(
        logger,
        "recovery_completed",
        status="completed",
        attempt_index=state.attempt_index,
        recovery_code="missing_evidence",
    )
    state.add_trace(
        "recovery",
        "start bounded replan",
        "completed",
        recovery_code="missing_evidence",
    )
    return state
