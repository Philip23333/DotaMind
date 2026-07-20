from app.agentic.runtime.clock import Clock
from app.agentic.runtime.summaries import build_attempt_record, resolve_terminal_outcome
from app.agentic.state import AgentRunState


def run_finalize_node(state: AgentRunState, clock: Clock) -> AgentRunState:
    state.add_trace("run_finalize", "finalize run and attempt", "planned")
    if state.run_context is None or state.run_budget is None:
        raise RuntimeError("run context is missing")
    if state.attempt_index != 0 or state.attempts:
        raise RuntimeError("V3.2-1 requires exactly one unfinalized attempt 0")
    if state.run_started_monotonic is None or state.attempt_started_monotonic is None:
        raise RuntimeError("monotonic run timing is missing")
    now = clock.monotonic()
    attempt_duration_ms = max(0, round((now - state.attempt_started_monotonic) * 1000))
    state.run_duration_ms = max(0, round((now - state.run_started_monotonic) * 1000))
    outcome = resolve_terminal_outcome(state)
    state.status = outcome.public_status
    state.response_type = outcome.response_type
    state.reason = outcome.stable_reason
    state.terminal_stage = outcome.terminal_stage
    state.attempt_failure_stage = outcome.failure_stage
    state.attempts.append(
        build_attempt_record(state, outcome, duration_ms=attempt_duration_ms)
    )
    state.add_trace("run_finalize", "run finalized", "completed")
    return state
