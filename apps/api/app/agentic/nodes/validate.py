from app.agentic.planning.contracts import validate_plan_against_catalog
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolRegistry


def validate_plan_node(
    state: AgentRunState,
    registry: ToolRegistry,
) -> AgentRunState:
    state.add_trace("validate", "validate execution plan", "planned")
    plan = state.plan
    if plan is None:
        state.status = "error"
        state.validation_failed = True
        state.attempt_failure_stage = "plan_validation"
        state.safe_failure_required = True
        state.errors.append("missing execution plan")
        state.add_trace("validate", "missing execution plan", "failed")
        return state

    errors = validate_plan_against_catalog(
        plan,
        registry,
        required_evidence=state.effective_required_evidence,
    )

    if errors:
        state.status = "error"
        state.validation_failed = True
        state.attempt_failure_stage = "plan_validation"
        state.safe_failure_required = True
        state.errors.extend(errors)
        state.add_trace("validate", "plan validation failed", "failed")
        return state

    state.status = "ok"
    state.add_trace("validate", "plan validation completed", "completed")
    return state
