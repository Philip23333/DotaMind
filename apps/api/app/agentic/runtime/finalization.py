from app.agentic.runtime.clock import Clock
from app.agentic.runtime.models import FailureStage, RuntimeFailureCode
from app.agentic.runtime.summaries import build_attempt_record, resolve_terminal_outcome
from app.agentic.state import AgentRunState


def finalize_attempt(state: AgentRunState, clock: Clock) -> AgentRunState:
    """Apply the single terminal-outcome resolver to the current attempt."""
    if state.run_context is None or state.run_budget is None:
        raise RuntimeError("run context is missing")
    if state.attempt_index not in {0, 1}:
        raise RuntimeError("attempt index must be 0 or 1")
    if state.attempt_index != len(state.attempts):
        raise RuntimeError("attempt records must be finalized in order")
    if state.attempt_started_monotonic is None:
        raise RuntimeError("attempt monotonic timing is missing")

    duration_ms = max(0, round((clock.monotonic() - state.attempt_started_monotonic) * 1000))
    outcome = resolve_terminal_outcome(state)
    state.status = outcome.public_status
    state.response_type = outcome.response_type
    state.reason = outcome.stable_reason
    state.terminal_stage = outcome.terminal_stage
    state.attempt_failure_stage = outcome.failure_stage
    state.attempts.append(build_attempt_record(state, outcome, duration_ms=duration_ms))
    return state


def finalize_run(state: AgentRunState, clock: Clock) -> AgentRunState:
    """Apply the same terminal-outcome resolver to the completed run."""
    if state.run_context is None or state.run_budget is None:
        raise RuntimeError("run context is missing")
    if len(state.attempts) not in {1, 2}:
        raise RuntimeError("run requires one or two finalized attempts")
    if [attempt.attempt_index for attempt in state.attempts] != list(range(len(state.attempts))):
        raise RuntimeError("attempt records must be contiguous")
    if state.attempt_index != len(state.attempts) - 1:
        raise RuntimeError("current attempt must already be finalized")
    if state.run_started_monotonic is None:
        raise RuntimeError("monotonic run timing is missing")

    state.run_duration_ms = max(0, round((clock.monotonic() - state.run_started_monotonic) * 1000))
    outcome = resolve_terminal_outcome(state)
    state.status = outcome.public_status
    state.response_type = outcome.response_type
    state.reason = outcome.stable_reason
    state.terminal_stage = outcome.terminal_stage
    state.attempt_failure_stage = outcome.failure_stage
    return state


def build_interrupted_summary(
    state: AgentRunState,
    clock: Clock,
    *,
    failure_code: RuntimeFailureCode,
    failure_stage: FailureStage,
    failed_node: str,
) -> AgentRunState:
    """Best-effort in-memory summary; never builds a public response."""
    summary = state.model_copy(deep=True)
    summary.runtime_failure_code = failure_code
    summary.attempt_failure_stage = failure_stage
    summary.status = "error"
    if summary.run_context is None or summary.run_budget is None:
        return summary

    try:
        if (
            failed_node != "attempt_finalize"
            and summary.attempt_index == len(summary.attempts)
            and summary.attempt_started_monotonic is not None
        ):
            finalize_attempt(summary, clock)
    except Exception:
        return summary

    try:
        if (
            failed_node != "run_finalize"
            and summary.attempts
            and summary.attempt_index == len(summary.attempts) - 1
            and summary.run_started_monotonic is not None
            and summary.run_duration_ms is None
        ):
            finalize_run(summary, clock)
    except Exception:
        return summary
    return summary
