from app.agentic.planning.controller import AgentController
from app.agentic.planning.decisions import ToolPlanDecision
from app.agentic.state import AgentRunState


async def controller_node(
    state: AgentRunState,
    controller: AgentController,
) -> AgentRunState:
    if state.run_budget is not None:
        state.run_budget.record_controller_call()
    if state.run_context is not None:
        state.run_context.prompt_versions = controller.prompt_versions
    state.add_trace("controller", "create controller decision", "planned")
    if state.recovery_feedback is None:
        result = await controller.decide(
            state.query,
            state.game,
            recent_messages=state.recent_messages or None,
            retrieved_messages=state.retrieved_messages or None,
            controller_context_summaries=state.controller_context_summaries or None,
            request_time=state.request_time.isoformat(),
        )
    else:
        if state.recovery_baseline_decision is None:
            raise RuntimeError("recovery baseline decision is missing")
        result = await controller.decide(
            state.query,
            state.game,
            recent_messages=state.recent_messages or None,
            retrieved_messages=state.retrieved_messages or None,
            controller_context_summaries=state.controller_context_summaries or None,
            request_time=state.request_time.isoformat(),
            recovery_feedback=state.recovery_feedback,
            recovery_baseline_decision=state.recovery_baseline_decision,
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
    return state
