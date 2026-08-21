"""Pure contract checks for the V3.3-2 Run lifecycle boundary."""

from app.application.chat_run_repository import (
    ACTIVE_RUN_STATUSES,
    RECOVERABLE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
)


def test_active_and_terminal_run_status_sets_are_closed_and_disjoint() -> None:
    assert ACTIVE_RUN_STATUSES == frozenset(
        {"queued", "running", "waiting_input", "cancel_requested"}
    )
    assert TERMINAL_RUN_STATUSES == frozenset(
        {"completed", "failed", "cancelled", "interrupted"}
    )
    assert ACTIVE_RUN_STATUSES.isdisjoint(TERMINAL_RUN_STATUSES)
    assert "waiting_input" not in RECOVERABLE_RUN_STATUSES
    assert ACTIVE_RUN_STATUSES | TERMINAL_RUN_STATUSES == {
        "queued",
        "running",
        "waiting_input",
        "cancel_requested",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
    }
