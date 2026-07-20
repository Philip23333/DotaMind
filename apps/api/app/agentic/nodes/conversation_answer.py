import logging

from app.agentic.planning.decisions import (
    ConversationAnswerResult,
    DirectAnswerDecision,
)
from app.agentic.state import AgentRunState

logger = logging.getLogger(__name__)


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

    turns = {turn.turn_index: turn for turn in state.history}
    if decision.response_mode == "social":
        summary = (decision.answer or "").strip()
    elif decision.response_mode == "quote_user_query":
        values = [turns[basis.turn_index].query for basis in decision.basis]
        summary = _render_numbered("你上次问的是", values)
    elif decision.response_mode == "recall_assistant_summary":
        values = [
            turns[basis.turn_index].response_summary for basis in decision.basis
        ]
        summary = _render_numbered("我当时的回答摘要是", values)
    else:
        values: list[str] = []
        for basis in decision.basis:
            turn = turns[basis.turn_index]
            values.extend(
                entity.name
                for entity in turn.resolved_entities
                if basis.entity_type is None or entity.type == basis.entity_type
            )
        unique_names = list(dict.fromkeys(values))
        if len(decision.basis) == 1:
            summary = f"你上次提到的是 {'、'.join(unique_names)}。"
        else:
            summary = _render_numbered("你之前提到的是", unique_names)

    state.answer = ConversationAnswerResult(
        summary=summary,
        conversation_basis=decision.basis,
    )
    state.status = "ok"
    state.add_trace("conversation_answer", "direct answer completed", "completed")
    logger.info("node=conversation_answer end mode=%s", decision.response_mode)
    return state


def _render_numbered(prefix: str, values: list[str]) -> str:
    if len(values) == 1:
        return f"{prefix}：{values[0]}"
    lines = "\n".join(f"{index}. {value}" for index, value in enumerate(values, 1))
    return f"{prefix}：\n{lines}"
