import logging

from app.agentic.planning.controller import AgentController
from app.agentic.planning.decisions import ToolPlanDecision
from app.agentic.state import AgentRunState

logger = logging.getLogger(__name__)


async def controller_node(
    state: AgentRunState,
    controller: AgentController,
) -> AgentRunState:
    if state.run_budget is not None:
        state.run_budget.record_controller_call()
    state.add_trace("controller", "create controller decision", "planned")
    logger.info(
        "node=controller start query_chars=%s game=%s history_turns=%s",
        len(state.query),
        state.game,
        len(state.history),
    )
    result = await controller.decide(
        state.query,
        state.game,
        history=state.history or None,
    )
    state.controller_result = result
    state.reason = result.reason
    if result.status != "decided" or result.decision is None:
        state.status = "error"
        state.errors = result.errors
        state.safe_failure_required = True
        state.validation_failed = result.failure_type == "decision_validation_error"
        state.attempt_failure_stage = (
            "decision_validation"
            if state.validation_failed
            else "controller"
        )
        state.add_trace(
            "controller",
            result.reason or result.failure_type or "controller error",
            "failed",
        )
        logger.info(
            "node=controller end status=error failure_type=%s errors=%s",
            result.failure_type,
            len(state.errors),
        )
        return state

    state.decision = result.decision
    state.decision_kind = result.decision.kind
    state.planner_required_evidence = (
        result.evidence_resolution.planner_required_evidence
    )
    state.global_required_evidence = (
        result.evidence_resolution.global_required_evidence
    )
    state.effective_required_evidence = (
        result.evidence_resolution.effective_required_evidence
    )
    state.required_evidence_sources = (
        result.evidence_resolution.required_evidence_sources
    )
    state.mandatory_evidence_by_call = (
        result.evidence_resolution.mandatory_evidence_by_call
    )
    if isinstance(result.decision, ToolPlanDecision):
        state.plan = result.decision.plan
    state.status = "ok"
    state.add_trace("controller", f"decision kind: {result.decision.kind}", "completed")
    logger.info(
        "node=controller end status=decided kind=%s tools=%s",
        result.decision.kind,
        len(state.plan.tool_calls) if state.plan else 0,
    )
    return state
