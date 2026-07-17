import logging

from app.agentic.planning.planner import AgenticPlanner
from app.agentic.state import AgentRunState

logger = logging.getLogger(__name__)


async def planner_node(state: AgentRunState, planner: AgenticPlanner) -> AgentRunState:
    state.add_trace("planner", "create execution plan", "planned")
    logger.info(
        "node=planner start query_chars=%s game=%s history_turns=%s",
        len(state.query),
        state.game,
        len(state.history),
    )
    planning = await planner.plan(state.query, state.game, history=state.history or None)
    state.planning = planning
    state.plan = planning.plan
    state.reason = planning.reason
    if planning.status != "planned" or planning.plan is None:
        state.status = planning.status
        state.errors = planning.errors
        state.add_trace("planner", planning.reason or planning.status, planning.status)
        logger.info(
            "node=planner end status=%s reason=%s errors=%s",
            state.status,
            state.reason,
            len(state.errors),
        )
        return state

    state.add_trace("planner", planning.reason or "plan accepted", "completed")
    state.status = "ok"
    logger.info(
        "node=planner end status=planned intent=%s tools=%s required_evidence=%s",
        planning.plan.intent,
        len(planning.plan.tool_calls),
        len(planning.plan.required_evidence),
    )
    return state
