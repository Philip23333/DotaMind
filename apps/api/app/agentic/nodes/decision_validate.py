from app.agentic.planning.decisions import (
    CapabilityBoundaryDecision,
    ClarificationDecision,
    ContextMissingDecision,
    DirectAnswerDecision,
    ToolPlanDecision,
    normalize_controller_decision,
    resolve_required_evidence,
    validate_controller_decision,
)
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolRegistry


def decision_validate_node(
    state: AgentRunState,
    registry: ToolRegistry,
) -> AgentRunState:
    state.add_trace("decision_validate", "validate controller decision", "planned")
    decision = state.decision
    if decision is None:
        state.status = "error"
        state.validation_failed = True
        state.attempt_failure_stage = "decision_validation"
        state.safe_failure_required = True
        state.errors.append("missing controller decision")
        state.add_trace("decision_validate", "missing decision", "failed")
        return state

    decision = normalize_controller_decision(decision)
    state.decision = decision
    state.decision_kind = decision.kind
    if isinstance(decision, ToolPlanDecision):
        state.plan = decision.plan
    evidence = (
        resolve_required_evidence(decision.plan, registry)
        if isinstance(decision, ToolPlanDecision)
        else None
    )
    errors = validate_controller_decision(
        decision,
        [*state.retrieved_messages, *state.recent_messages],
        registry,
        evidence,
        current_query=state.query,
    )
    if errors:
        state.status = "error"
        state.validation_failed = True
        state.attempt_failure_stage = "decision_validation"
        state.safe_failure_required = True
        state.errors.extend(errors)
        state.add_trace("decision_validate", "decision validation failed", "failed")
        return state

    if evidence is not None:
        state.planner_required_evidence = evidence.planner_required_evidence
        state.global_required_evidence = evidence.global_required_evidence
        state.effective_required_evidence = evidence.effective_required_evidence
        state.required_evidence_sources = evidence.required_evidence_sources
        state.mandatory_evidence_by_call = evidence.mandatory_evidence_by_call

    if isinstance(decision, DirectAnswerDecision):
        state.status = "ok"
        state.reason = ""
    elif isinstance(decision, ClarificationDecision):
        state.status = "clarification_required"
        state.reason = decision.question
        state.missing_fields = list(decision.missing_fields)
    elif isinstance(decision, ContextMissingDecision):
        state.status = "insufficient_context"
        state.reason = decision.reason
    elif isinstance(decision, CapabilityBoundaryDecision):
        state.status = "insufficient_tools"
        state.reason = decision.reason
    else:
        state.status = "ok"
        state.plan = decision.plan

    state.add_trace("decision_validate", "decision validation completed", "completed")
    return state
