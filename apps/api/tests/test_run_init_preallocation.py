"""Run ID preallocation contract tests."""

from datetime import UTC, datetime
from uuid import uuid4

from app.agentic.nodes.run_init import run_init_node
from app.agentic.runtime.clock import FakeClock
from app.agentic.state import AgentRunState
from app.core.config import RuntimePolicy


def test_run_init_reuses_preallocated_internal_run_id() -> None:
    run_id = uuid4()
    state = AgentRunState(
        query="q",
        game="dota2",
        internal_run_id=run_id,
    )

    run_init_node(
        state,
        RuntimePolicy(),
        FakeClock(datetime(2026, 8, 5, tzinfo=UTC)),
    )

    assert state.run_context is not None
    assert state.run_context.run_id == run_id
