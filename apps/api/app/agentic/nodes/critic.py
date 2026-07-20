import logging

from app.agentic.critic.reviewer import AgenticCritic
from app.agentic.state import AgentRunState

logger = logging.getLogger(__name__)


def critic_node(state: AgentRunState, critic: AgenticCritic) -> AgentRunState:
    state.add_trace("critic", "review plan evidence and answer", "planned")
    logger.info("node=critic start has_answer=%s", state.answer is not None)
    if state.plan is None or state.evidence_graph is None or state.answer is None:
        state.status = "error"
        state.errors.append("missing critic inputs")
        state.add_trace("critic", "missing critic inputs", "failed")
        logger.info("node=critic end status=error errors=%s", len(state.errors))
        return state

    state.review = critic.review(state.plan, state.evidence_graph, state.answer)
    state.add_trace(
        "critic",
        f"review severity: {state.review.severity}",
        "completed" if state.review.passed else "failed",
    )
    logger.info(
        "node=critic end severity=%s reasons=%s passed=%s",
        state.review.severity,
        len(state.review.reasons),
        state.review.passed,
    )
    return state
