from app.agentic.runtime.clock import Clock
from app.agentic.runtime.finalization import finalize_attempt
from app.agentic.state import AgentRunState


def attempt_finalize_node(state: AgentRunState, clock: Clock) -> AgentRunState:
    state.add_trace("attempt_finalize", "attempt_finalize", "planned")
    finalize_attempt(state, clock)
    state.add_trace("attempt_finalize", "attempt finalized", "completed")
    return state
