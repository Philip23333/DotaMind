from app.agentic.runtime.clock import Clock
from app.agentic.runtime.summaries import build_attempt_record, resolve_terminal_outcome
from app.agentic.state import AgentRunState


def attempt_finalize_node(state: AgentRunState, clock: Clock) -> AgentRunState:
    state.add_trace("attempt_finalize", "finalize current attempt", "planned")
    if state.run_context is None or state.run_budget is None:
        raise RuntimeError("run context is missing")
    if state.attempt_index not in {0, 1}:
        raise RuntimeError("attempt index must be 0 or 1")
    if state.attempt_index != len(state.attempts):
        raise RuntimeError("attempt records must be finalized in order")
    if state.attempt_started_monotonic is None:
        raise RuntimeError("attempt monotonic timing is missing")

    duration_ms = max(
        0,
        round((clock.monotonic() - state.attempt_started_monotonic) * 1000),
    )
    outcome = resolve_terminal_outcome(state)
    state.status = outcome.public_status
    state.response_type = outcome.response_type
    state.reason = outcome.stable_reason
    state.terminal_stage = outcome.terminal_stage
    state.attempt_failure_stage = outcome.failure_stage
    state.attempts.append(build_attempt_record(state, outcome, duration_ms=duration_ms))
    state.add_trace("attempt_finalize", "attempt finalized", "completed")
    return state
