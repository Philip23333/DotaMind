from app.agentic.planning.decisions import DirectAnswerDecision, DirectAnswerResult
from app.agentic.state import AgentRunState


def conversation_answer_node(state: AgentRunState) -> AgentRunState:
    """Accept the Controller-authored direct answer without another model call."""
    state.add_trace("conversation_answer", "render direct answer", "planned")
    decision = state.decision
    if not isinstance(decision, DirectAnswerDecision):
        state.status = "error"
        state.validation_failed = True
        state.attempt_failure_stage = "conversation_answer"
        state.safe_failure_required = True
        state.errors.append("direct answer node received incompatible decision")
        state.add_trace("conversation_answer", "invalid decision", "failed")
        return state

    state.answer = DirectAnswerResult(summary=decision.answer)
    state.status = "ok"
    state.add_trace("conversation_answer", "direct answer completed", "completed")
    return state
