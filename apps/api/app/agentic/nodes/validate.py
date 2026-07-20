import logging

from app.agentic.planning.contracts import validate_plan_against_catalog
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolRegistry

logger = logging.getLogger(__name__)


def validate_plan_node(state: AgentRunState, registry: ToolRegistry) -> AgentRunState:
    state.add_trace("validate", "validate execution plan", "planned")
    logger.info("node=validate start has_plan=%s", state.plan is not None)
    plan = state.plan
    if plan is None:
        state.status = "error"
        state.validation_failed = True
        state.attempt_failure_stage = "plan_validation"
        state.safe_failure_required = True
        state.errors.append("missing execution plan")
        state.add_trace("validate", "missing execution plan", "failed")
        logger.info("node=validate end status=error errors=%s", len(state.errors))
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
        logger.info("node=validate end status=error errors=%s", len(state.errors))
        return state

    state.status = "ok"
    state.add_trace("validate", "plan validation completed", "completed")
    logger.info("node=validate end status=ok tools=%s", len(plan.tool_calls))
    return state
