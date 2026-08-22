from app.agentic.answer.synthesizer import AnswerSynthesizer
from app.agentic.runtime.streaming import (
    AnswerDeltaStreamEvent,
    bind_observer_attempt_index,
    publish_stream_event,
    reset_observer_attempt_index,
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

    # Tool mandatory evidence remains available to runtime/Critic validation,
    # but Answer should see only the planner/contract evidence requested for
    # the current response.
    answer_graph = state.evidence_graph.model_copy(
        update={"required_evidence": list(state.global_required_evidence)}
    )

    if state.run_budget is not None:
        state.run_budget.record_answer_call()
    observer_token = bind_observer_attempt_index(state.attempt_index)
    try:
        if stream_events_enabled():
            state.answer = await synthesizer.synthesize(
                state.plan,
                answer_graph,
                current_query=state.query,
                on_delta=lambda delta: publish_stream_event(
                    AnswerDeltaStreamEvent(delta=delta, attempt_index=state.attempt_index)
                ),
            )
        else:
            state.answer = await synthesizer.synthesize(
                state.plan,
                answer_graph,
                current_query=state.query,
            )
    finally:
        reset_observer_attempt_index(observer_token)
    trace_status = (
        "failed"
        if state.answer.status in {"error", "insufficient_evidence"}
        else "completed"
    )
    state.add_trace("answer", f"answer status: {state.answer.status}", trace_status)
    return state
