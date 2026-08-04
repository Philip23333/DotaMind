from app.agentic.critic.reviewer import AgenticCritic
from app.agentic.state import AgentRunState


def critic_node(state: AgentRunState, critic: AgenticCritic) -> AgentRunState:
    state.add_trace("critic", "review plan evidence and answer", "planned")
    if state.plan is None or state.evidence_graph is None or state.answer is None:
        state.status = "error"
        state.errors.append("missing critic inputs")
        state.add_trace("critic", "missing critic inputs", "failed")
        return state

    state.review = critic.review(state.plan, state.evidence_graph, state.answer)
    state.add_trace(
        "critic",
        f"review severity: {state.review.severity}",
        "completed" if state.review.passed else "failed",
    )
    return state
