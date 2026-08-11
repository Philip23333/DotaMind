from app.agentic.planning.decisions import (
    ConversationAnswerResult,
    DirectAnswerDecision,
)
from app.agentic.state import AgentRunState


def conversation_answer_node(state: AgentRunState) -> AgentRunState:
    """Render validated conversation recall without another model call."""
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

    messages = {
        (message.turn_index, message.role): message
        for message in [*state.retrieved_messages, *state.recent_messages]
    }
    if decision.response_mode == "social":
        summary = (decision.answer or "").strip()
    elif decision.response_mode == "quote_user_query":
        values = [messages[(basis.turn_index, "user")].content for basis in decision.basis]
        summary = _render_numbered("你上次问的是", values)
    elif decision.response_mode == "recall_assistant_summary":
        values = [
            messages[(basis.turn_index, "assistant")].content
            for basis in decision.basis
        ]
        summary = _render_numbered("我当时的回答摘要是", values)

    state.answer = ConversationAnswerResult(
        summary=summary,
        conversation_basis=decision.basis,
    )
    state.status = "ok"
    state.add_trace("conversation_answer", "direct answer completed", "completed")
    return state

def _render_numbered(prefix: str, values: list[str]) -> str:
    if len(values) == 1:
        return f"{prefix}：{values[0]}"
    lines = "\n".join(f"{index}. {value}" for index, value in enumerate(values, 1))
    return f"{prefix}：\n{lines}"
