import logging

from app.agentic.answer.synthesizer import AnswerSynthesizer
from app.agentic.planning.contracts import get_contract
from app.agentic.state import AgentRunState

logger = logging.getLogger(__name__)


async def answer_node(
    state: AgentRunState,
    synthesizer: AnswerSynthesizer,
) -> AgentRunState:
    state.add_trace("answer", "synthesize structured answer", "planned")
    structured_contract = (
        state.plan is not None
        and (contract := get_contract(state.plan.output_contract)) is not None
        and contract.structured
    )
    logger.info(
        "node=answer start has_graph=%s structured_contract=%s output_contract=%s",
        state.evidence_graph is not None,
        structured_contract,
        state.plan.output_contract if state.plan else None,
    )
    if state.plan is None or state.evidence_graph is None:
        state.status = "error"
        state.errors.append("missing plan or evidence graph for answer synthesis")
        state.add_trace("answer", "missing answer inputs", "failed")
        logger.info("node=answer end status=error errors=%s", len(state.errors))
        return state

    if state.run_budget is not None:
        state.run_budget.record_answer_call()
    state.answer = await synthesizer.synthesize(state.plan, state.evidence_graph)
    trace_status = (
        "failed"
        if state.answer.status in {"error", "insufficient_evidence"}
        else "completed"
    )
    state.add_trace("answer", f"answer status: {state.answer.status}", trace_status)
    logger.info(
        "node=answer end status=%s recommendations=%s confidence=%.2f",
        state.answer.status,
        len(state.answer.recommendations),
        state.answer.confidence,
    )
    return state
