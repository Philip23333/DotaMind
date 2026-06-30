import logging

from app.agentic.planning.contracts import get_contract
from app.agentic.state import AgentRunState

logger = logging.getLogger(__name__)


def response_node(state: AgentRunState) -> AgentRunState:
    state.response_type = _response_type(state)
    logger.info(
        "node=response start status=%s type=%s errors=%s has_answer=%s has_review=%s",
        state.status,
        state.response_type,
        len(state.errors),
        state.answer is not None,
        state.review is not None,
    )
    state.response = state.model_dump(
        mode="json",
        include={
            "query",
            "game",
            "status",
            "reason",
            "response_type",
            "plan",
            "tool_results",
            "evidence_graph",
            "answer",
            "review",
            "errors",
            "trace",
        },
    )
    state.response["planner_output"] = (
        state.planning.raw_output if state.planning is not None else None
    )
    state.response["planner_raw_content"] = (
        state.planning.raw_content if state.planning is not None else None
    )
    state.response["planner_finish_reason"] = (
        state.planning.finish_reason if state.planning is not None else None
    )
    logger.info("node=response end response_ready=true")
    return state


def _response_type(state: AgentRunState) -> str:
    if state.status == "insufficient_tools":
        return "capability_boundary"
    if state.status == "error":
        return "execution_error"
    if state.answer is None:
        return "raw_tool_results"
    if state.answer.status == "insufficient_evidence":
        return "insufficient_evidence"
    if state.answer.status == "error":
        return "answer_error"
    contract = get_contract(state.answer.answer_type)
    if state.answer.status == "ok" and contract is not None:
        return state.answer.answer_type
    if state.answer.status == "unsupported_output_contract":
        return "unsupported_answer"
    return "raw_tool_results"
