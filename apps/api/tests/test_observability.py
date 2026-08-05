import logging
import math

import pytest

from app.failure_codes import STABLE_FAILURE_CODES, normalize_failure_code
from app.observability import (
    ATTEMPTS,
    CHAT_RUN_CANCELLATIONS,
    CHAT_RUN_DURATION,
    CHAT_RUN_EVENT_BUS_ERRORS,
    CHAT_RUN_EVENTS,
    CHAT_RUN_STALE_INTERRUPTED,
    CHAT_RUN_SUBSCRIPTIONS,
    CHAT_RUNS,
    CONTROLLER_CALLS,
    EVIDENCE_COMPLETENESS,
    IDEMPOTENCY,
    LATENCY_BUCKETS,
    LOCK_WAIT,
    RUN_DURATION,
    RUNS,
    SESSION_OPERATIONS,
    TOOL_CALL_DURATION,
    TOOL_CALLS,
    emit_event,
)


def test_failure_code_catalog_is_closed_and_unknown_values_are_normalized() -> None:
    assert len(STABLE_FAILURE_CODES) == 16
    assert normalize_failure_code("lock_lost") == "lock_lost"
    assert normalize_failure_code("UnexpectedError") == "execution_error"
    assert normalize_failure_code({"error": "secret"}) == "execution_error"


def test_prometheus_contract_has_exact_labels_and_latency_buckets() -> None:
    assert RUNS._labelnames == ("status", "response_type")
    assert RUN_DURATION._labelnames == ("status",)
    assert ATTEMPTS._labelnames == ("status", "failure_stage", "recovery_code")
    assert CONTROLLER_CALLS._labelnames == ("status", "failure_code")
    assert TOOL_CALLS._labelnames == ("tool_name", "status", "reused")
    assert TOOL_CALL_DURATION._labelnames == ("tool_name", "status")
    assert EVIDENCE_COMPLETENESS._labelnames == ("status",)
    assert SESSION_OPERATIONS._labelnames == (
        "backend",
        "operation",
        "status",
        "failure_code",
    )
    assert LOCK_WAIT._labelnames == ("status",)
    assert IDEMPOTENCY._labelnames == ("backend", "action")
    assert CHAT_RUNS._labelnames == ("status",)
    assert CHAT_RUN_DURATION._labelnames == ("status",)
    assert CHAT_RUN_EVENTS._labelnames == ("operation",)
    assert CHAT_RUN_EVENT_BUS_ERRORS._labelnames == ("operation",)
    assert CHAT_RUN_CANCELLATIONS._labelnames == ("outcome",)
    assert CHAT_RUN_SUBSCRIPTIONS._labelnames == ()
    assert CHAT_RUN_STALE_INTERRUPTED._labelnames == ()
    assert tuple(RUN_DURATION._upper_bounds[:-1]) == LATENCY_BUCKETS
    assert math.isinf(RUN_DURATION._upper_bounds[-1])
    assert tuple(EVIDENCE_COMPLETENESS._upper_bounds[:-1]) == (0, 0.25, 0.5, 0.75, 1)


def test_runtime_log_helper_rejects_unknown_events_fields_and_payloads(caplog) -> None:
    logger = logging.getLogger("tests.runtime_event")
    caplog.set_level(logging.INFO, logger=logger.name)

    emit_event(
        logger,
        "tool_call_failed",
        status="error\nnext-line",
        failure_code="unknown-exception-name",
        tool_name="safe_tool",
        tool_call_id="full-sensitive-call-id",
    )

    assert "next-line" in caplog.text
    assert "\nnext-line" not in caplog.text
    assert "failure_code=execution_error" in caplog.text
    assert "tool_call_id=fullsens" in caplog.text
    assert "full-sensitive-call-id" not in caplog.text

    with pytest.raises(ValueError, match="unsupported runtime event"):
        emit_event(logger, "arbitrary_event", status="error")
    with pytest.raises(ValueError, match="unsupported runtime log fields"):
        emit_event(logger, "agent_run_failed", query="secret query")
    with pytest.raises(TypeError, match="unsupported structured log field"):
        emit_event(logger, "agent_run_failed", node={"payload": "secret"})
