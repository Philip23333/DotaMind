"""Stable, low-cardinality failure codes shared across runtime boundaries."""

from typing import Literal, cast

StableFailureCode = Literal[
    "planning_error",
    "decision_validation_error",
    "tool_error",
    "answer_error",
    "execution_error",
    "execution_budget_error",
    "execution_timeout",
    "insufficient_evidence",
    "replan_exhausted",
    "request_cancelled",
    "idempotency_conflict",
    "session_store_error",
    "unavailable",
    "lock_timeout",
    "lock_lost",
    "data_invalid",
]

STABLE_FAILURE_CODES = frozenset(StableFailureCode.__args__)


def normalize_failure_code(value: object) -> StableFailureCode:
    """Map arbitrary values to the closed telemetry failure-code catalog."""
    if isinstance(value, str) and value in STABLE_FAILURE_CODES:
        return cast(StableFailureCode, value)
    return "execution_error"
