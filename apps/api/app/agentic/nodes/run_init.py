from datetime import timedelta
from uuid import uuid4

from app.agentic.runtime.clock import Clock
from app.agentic.runtime.models import RunBudget, RunContext
from app.agentic.state import AgentRunState
from app.core.config import RuntimePolicy


def run_init_node(
    state: AgentRunState,
    policy: RuntimePolicy,
    clock: Clock,
) -> AgentRunState:
    if state.run_context is not None:
        raise RuntimeError("run context already exists")
    started_at = clock.now_utc()
    started_monotonic = clock.monotonic()
    state.run_context = RunContext(
        run_id=state.internal_run_id or uuid4(),
        request_id=state.internal_request_id,
        session_id=state.internal_session_id,
        started_at=started_at,
        deadline_at=started_at + timedelta(seconds=policy.max_elapsed_seconds),
        prompt_versions={},
    )
    state.run_budget = RunBudget(**policy.model_dump())
    state.run_started_monotonic = started_monotonic
    state.attempt_index = 0
    state.attempt_started_at = started_at
    state.attempt_started_monotonic = started_monotonic
    state.attempts = []
    state.add_trace("run_init", "initialize run and attempt", "planned")
    state.add_trace("run_init", "run initialized", "completed")
    return state
