from app.agentic.runtime.clock import Clock
from app.agentic.runtime.finalization import finalize_run
from app.agentic.state import AgentRunState


def run_finalize_node(state: AgentRunState, clock: Clock) -> AgentRunState:
    state.add_trace("run_finalize", "run_finalize", "planned")
    finalize_run(state, clock)
    state.add_trace("run_finalize", "run finalized", "completed")
    return state
