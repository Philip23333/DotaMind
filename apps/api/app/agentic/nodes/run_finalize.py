from app.agentic.runtime.clock import Clock
from app.agentic.runtime.summaries import resolve_terminal_outcome
from app.agentic.state import AgentRunState


def run_finalize_node(state: AgentRunState, clock: Clock) -> AgentRunState:
    state.add_trace("run_finalize", "finalize run", "planned")
    if state.run_context is None or state.run_budget is None:
        raise RuntimeError("run context is missing")
    if len(state.attempts) not in {1, 2}:
        raise RuntimeError("run requires one or two finalized attempts")
    if [attempt.attempt_index for attempt in state.attempts] != list(
        range(len(state.attempts))
    ):
        raise RuntimeError("attempt records must be contiguous")
    if state.attempt_index != len(state.attempts) - 1:
        raise RuntimeError("current attempt must already be finalized")
    if state.run_started_monotonic is None:
        raise RuntimeError("monotonic run timing is missing")
    now = clock.monotonic()
    state.run_duration_ms = max(0, round((now - state.run_started_monotonic) * 1000))
    outcome = resolve_terminal_outcome(state)
    state.status = outcome.public_status
    state.response_type = outcome.response_type
    state.reason = outcome.stable_reason
    state.terminal_stage = outcome.terminal_stage
    state.attempt_failure_stage = outcome.failure_stage
    state.add_trace("run_finalize", "run finalized", "completed")
    return state
