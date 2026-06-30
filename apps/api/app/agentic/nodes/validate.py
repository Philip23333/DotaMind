import logging

from app.agentic.state import AgentRunState

logger = logging.getLogger(__name__)


def validate_plan_node(state: AgentRunState) -> AgentRunState:
    state.add_trace("validate", "validate execution plan", "planned")
    logger.info("node=validate start has_plan=%s", state.plan is not None)
    plan = state.plan
    if plan is None:
        state.status = "error"
        state.errors.append("missing execution plan")
        state.add_trace("validate", "missing execution plan", "failed")
        logger.info("node=validate end status=error errors=%s", len(state.errors))
        return state

    errors = []
    if len(plan.tool_calls) > plan.constraints.max_tool_calls:
        errors.append(
            "plan exceeds max_tool_calls "
            f"({len(plan.tool_calls)} > {plan.constraints.max_tool_calls})"
        )

    seen = set()
    for call in plan.tool_calls:
        if call.id in seen:
            errors.append(f"duplicate tool call id: {call.id}")
        seen.add(call.id)

    if errors:
        state.status = "error"
        state.errors.extend(errors)
        state.add_trace("validate", "plan validation failed", "failed")
        logger.info("node=validate end status=error errors=%s", len(state.errors))
        return state

    state.status = "ok"
    state.add_trace("validate", "plan validation completed", "completed")
    logger.info("node=validate end status=ok tools=%s", len(plan.tool_calls))
    return state
