import logging

from app.agentic.conversation.summary import SESSION_REQUEST_FAILED_REASON
from app.agentic.planning.contracts import get_contract
from app.agentic.planning.decisions import ConversationAnswerResult
from app.agentic.state import AgentRunState

logger = logging.getLogger(__name__)


def response_node(state: AgentRunState) -> AgentRunState:
    _apply_terminal_priority(state)
    state.response_type = _response_type(state)
    state.reason = _terminal_reason(state)
    logger.info(
        "node=response start status=%s type=%s errors=%s has_answer=%s has_review=%s",
        state.status,
        state.response_type,
        len(state.errors),
        state.answer is not None,
        state.review is not None,
    )
    if state.safe_failure_required:
        response_type = state.response_type or "decision_validation_error"
        state.response = {
            "query": state.query,
            "game": state.game,
            "status": "error",
            "reason": SESSION_REQUEST_FAILED_REASON,
            "response_type": response_type,
            "error_code": response_type,
            "decision_kind": None,
            "missing_fields": [],
            "planner_required_evidence": [],
            "effective_required_evidence": [],
            "required_evidence_sources": {},
            "plan": None,
            "tool_results": [],
            "evidence_graph": None,
            "answer": None,
            "review": None,
            "errors": [],
            "trace": [],
        }
        logger.info("node=response end response_ready=true safe_failure=true")
        return state

    state.response = state.model_dump(
        mode="json",
        include={
            "query",
            "game",
            "status",
            "reason",
            "response_type",
            "decision_kind",
            "missing_fields",
            "planner_required_evidence",
            "effective_required_evidence",
            "required_evidence_sources",
            "plan",
            "tool_results",
            "evidence_graph",
            "answer",
            "review",
            "errors",
            "trace",
        },
    )
    state.response["error_code"] = (
        state.response_type if state.status == "error" else None
    )
    logger.info("node=response end response_ready=true")
    return state


def _apply_terminal_priority(state: AgentRunState) -> None:
    """Apply one deterministic top-level status/error ordering."""
    result = state.controller_result
    if result is not None and result.status == "error":
        state.status = "error"
        return
    if state.validation_failed:
        state.status = "error"
        return
    if any(item.status == "error" for item in state.tool_results):
        state.status = "error"
        return
    if state.answer is not None and state.answer.status == "error":
        state.status = "error"
        return
    if state.evidence_graph is not None and state.evidence_graph.missing:
        state.status = "insufficient_evidence"
        return
    if state.answer is not None and state.answer.status == "insufficient_evidence":
        state.status = "insufficient_evidence"
        return
    if state.review is not None and not state.review.passed:
        state.status = "insufficient_evidence"


def _response_type(state: AgentRunState) -> str:
    result = state.controller_result
    if result is not None and result.status == "error":
        return result.failure_type or "planning_error"
    if state.validation_failed:
        return "decision_validation_error"
    if any(item.status == "error" for item in state.tool_results):
        return "tool_error"
    if state.answer is not None and state.answer.status == "error":
        return "answer_error"
    if state.status == "insufficient_evidence":
        return "insufficient_evidence"
    if state.status == "clarification_required":
        return "clarification"
    if state.status == "insufficient_context":
        return "conversation_context_missing"
    if state.status == "insufficient_tools":
        return "capability_boundary"
    if isinstance(state.answer, ConversationAnswerResult):
        return "direct_answer"
    if state.status == "error":
        return "execution_error"
    if state.answer is None:
        return "raw_tool_results"
    if state.answer.status == "insufficient_evidence":
        return "insufficient_evidence"
    contract = get_contract(state.answer.answer_type)
    if state.answer.status == "ok" and contract is not None:
        return state.answer.answer_type
    if state.answer.status == "unsupported_output_contract":
        return "unsupported_answer"
    return "raw_tool_results"


def _terminal_reason(state: AgentRunState) -> str:
    stable_reasons = {
        "planning_error": "planning failed",
        "decision_validation_error": "decision validation failed",
        "tool_error": "tool execution failed",
        "answer_error": "answer generation failed",
        "execution_error": "execution failed",
        "insufficient_evidence": "insufficient evidence",
    }
    return stable_reasons.get(state.response_type or "", state.reason)
