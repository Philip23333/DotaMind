from app.agentic.answer.synthesizer import AnswerSynthesizer
from app.agentic.runtime.streaming import (
    AnswerDeltaStreamEvent,
    publish_stream_event,
    stream_events_enabled,
)
from app.agentic.state import AgentRunState


async def answer_node(
    state: AgentRunState,
    synthesizer: AnswerSynthesizer,
) -> AgentRunState:
    state.add_trace("answer", "synthesize structured answer", "planned")
    if state.plan is None or state.evidence_graph is None:
        state.status = "error"
        state.errors.append("missing plan or evidence graph for answer synthesis")
        state.add_trace("answer", "missing answer inputs", "failed")
        return state

    if state.run_budget is not None:
        state.run_budget.record_answer_call()
    if stream_events_enabled():
        state.answer = await synthesizer.synthesize(
            state.plan,
            state.evidence_graph,
            current_query=state.query,
            on_delta=lambda delta: publish_stream_event(
                AnswerDeltaStreamEvent(delta=delta, attempt_index=state.attempt_index)
            ),
        )
    else:
        state.answer = await synthesizer.synthesize(
            state.plan,
            state.evidence_graph,
            current_query=state.query,
        )
    trace_status = (
        "failed"
        if state.answer.status in {"error", "insufficient_evidence"}
        else "completed"
    )
    state.add_trace("answer", f"answer status: {state.answer.status}", trace_status)
    return state
