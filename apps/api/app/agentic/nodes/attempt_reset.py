from app.agentic.runtime.clock import Clock
from app.agentic.runtime.guards import apply_runtime_failure, runtime_gate_failure
from app.agentic.runtime.reset import reset_attempt_working_state
from app.agentic.state import AgentRunState


def attempt_reset_node(state: AgentRunState, clock: Clock) -> AgentRunState:
    state.add_trace("attempt_reset", "start recovery attempt", "planned")
    if state.recovery_action != "replan" or state.attempt_index != 0:
        raise RuntimeError("attempt reset requires recovery from attempt 0")
    if len(state.attempts) != 1:
        raise RuntimeError("attempt 0 must be finalized before reset")

    gate_failure = runtime_gate_failure(state, clock)
    if gate_failure is not None:
        apply_runtime_failure(state, gate_failure)
        state.recovery_action = "terminal"
        state.add_trace("attempt_reset", state.reason, "failed")
        return state

    state.add_trace("attempt_reset", "recovery attempt started", "completed")
    return reset_attempt_working_state(
        state,
        next_attempt_index=1,
        started_at=clock.now_utc(),
        started_monotonic=clock.monotonic(),
    )
