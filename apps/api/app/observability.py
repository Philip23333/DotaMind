"""Low-cardinality telemetry for one API process / one scrape target."""

import logging

from prometheus_client import Counter, Gauge, Histogram

from app.failure_codes import normalize_failure_code

LATENCY_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1,
    2.5,
    5,
    10,
    30,
    60,
)

RUNS = Counter(
    "dotamind_agent_runs_total",
    "Agent runs by final runtime outcome.",
    ("status", "response_type"),
)
RUN_DURATION = Histogram(
    "dotamind_agent_run_duration_seconds",
    "Agent run duration.",
    ("status",),
    buckets=LATENCY_BUCKETS,
)
ATTEMPTS = Counter(
    "dotamind_agent_attempts_total",
    "Finalized agent attempts.",
    ("status", "failure_stage", "recovery_code"),
)
CONTROLLER_CALLS = Counter(
    "dotamind_controller_calls_total",
    "Controller calls by stable outcome.",
    ("status", "failure_code"),
)
TOOL_CALLS = Counter(
    "dotamind_tool_calls_total",
    "Tool calls and cache reuses by stable outcome.",
    ("tool_name", "status", "reused"),
)
TOOL_CALL_DURATION = Histogram(
    "dotamind_tool_call_duration_seconds",
    "Real tool dispatch duration; reused calls are excluded.",
    ("tool_name", "status"),
    buckets=LATENCY_BUCKETS,
)
EVIDENCE_COMPLETENESS = Histogram(
    "dotamind_evidence_completeness",
    "Evidence completeness after an attempt.",
    ("status",),
    buckets=(0, 0.25, 0.5, 0.75, 1),
)
CRITIC_REVIEWS = Counter(
    "dotamind_critic_reviews_total",
    "Critic reviews by stable severity.",
    ("severity",),
)
RECOVERY = Counter(
    "dotamind_recovery_total",
    "Bounded recovery decisions.",
    ("outcome", "recovery_code"),
)
BUDGET = Counter(
    "dotamind_budget_exhausted_total",
    "Runtime budget guard rejections.",
    ("resource",),
)
SESSION_OPERATIONS = Counter(
    "dotamind_session_store_operations_total",
    "Session-store operations by backend and stable outcome.",
    ("backend", "operation", "status", "failure_code"),
)
LOCK_WAIT = Histogram(
    "dotamind_session_lock_wait_seconds",
    "Time spent waiting for a session lock.",
    ("status",),
    buckets=LATENCY_BUCKETS,
)
IDEMPOTENCY = Counter(
    "dotamind_idempotency_total",
    "Stateful request-id actions.",
    ("backend", "action"),
)
CHAT_RUNS = Counter(
    "dotamind_chat_runs_total",
    "Chat Runs by durable terminal status.",
    ("status",),
)
CHAT_RUN_DURATION = Histogram(
    "dotamind_chat_run_duration_seconds",
    "Chat Run wall-clock duration.",
    ("status",),
    buckets=LATENCY_BUCKETS,
)
CHAT_RUN_EVENTS = Counter(
    "dotamind_chat_run_events_total",
    "Chat Run event bus operations.",
    ("operation",),
)
CHAT_RUN_EVENT_BUS_ERRORS = Counter(
    "dotamind_chat_run_event_bus_errors_total",
    "Chat Run event bus failures by stable operation.",
    ("operation",),
)
CHAT_RUN_SUBSCRIPTIONS = Gauge(
    "dotamind_chat_run_subscriptions",
    "Current Chat Run event subscriptions.",
)
CHAT_RUN_CANCELLATIONS = Counter(
    "dotamind_chat_run_cancellations_total",
    "Chat Run cancellation outcomes.",
    ("outcome",),
)
CHAT_RUN_STALE_INTERRUPTED = Counter(
    "dotamind_chat_run_stale_interrupted_total",
    "Chat Runs interrupted by stale recovery.",
)
RUNTIME_EVENTS = frozenset(
    {
        "agent_run_started",
        "agent_run_completed",
        "agent_run_failed",
        "agent_run_cancelled",
        "agent_run_waiting_input",
        "agent_attempt_finalized",
        "controller_completed",
        "controller_failed",
        "tool_call_completed",
        "tool_call_failed",
        "tool_call_reused",
        "recovery_started",
        "recovery_completed",
        "recovery_exhausted",
        "request_replayed",
        "request_conflict",
        "request_takeover",
        "request_commit_failed",
        "request_commit_cancelled",
        "session_lock_acquired",
        "session_lock_timeout",
        "session_lock_lost",
        "session_store_failed",
    }
)
LOG_FIELD_ORDER = (
    "status",
    "run_id_prefix",
    "attempt_index",
    "node",
    "duration_ms",
    "failure_stage",
    "failure_code",
    "tool_name",
    "tool_call_id",
    "reused",
    "recovery_code",
    "backend",
    "operation",
    "lock_wait_ms",
)
LOG_FIELDS = frozenset(LOG_FIELD_ORDER)
WARNING_EVENTS = frozenset(
    {
        "agent_run_failed",
        "agent_run_cancelled",
        "controller_failed",
        "tool_call_failed",
        "recovery_exhausted",
        "request_commit_failed",
        "request_commit_cancelled",
        "session_lock_timeout",
        "session_lock_lost",
        "session_store_failed",
    }
)


def id_prefix(value: object) -> str:
    """Return the only identifier shape allowed in runtime logs."""
    return str(value).replace("-", "")[:8].lower()


def emit_event(logger: logging.Logger, event: str, **fields: object) -> None:
    """Emit one allowlisted, single-line key-value runtime event."""
    if event not in RUNTIME_EVENTS:
        raise ValueError(f"unsupported runtime event: {event}")
    unknown = set(fields) - LOG_FIELDS
    if unknown:
        raise ValueError(f"unsupported runtime log fields: {sorted(unknown)}")

    rendered = [f"event={event}"]
    for key in LOG_FIELD_ORDER:
        value = fields.get(key)
        if value is None:
            continue
        if key == "failure_code":
            value = normalize_failure_code(value)
        if key in {"run_id_prefix", "tool_call_id"}:
            value = id_prefix(value)
        rendered.append(f"{key}={_render_log_value(key, value)}")
    log = logger.warning if event in WARNING_EVENTS else logger.info
    log(" ".join(rendered))


def _render_log_value(key: str, value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        raise TypeError(f"unsupported structured log field: {key}")
    text = "_".join(value.replace("\r", " ").replace("\n", " ").split())[:96]
    return text or "none"


def record_run(
    state,
    *,
    status: str | None = None,
    response_type: str | None = None,
    duration_ms: int | None = None,
) -> None:
    final_status = status or state.status
    final_response_type = response_type or state.response_type or "execution_error"
    final_duration_ms = duration_ms if duration_ms is not None else state.run_duration_ms
    RUNS.labels(final_status, final_response_type).inc()
    RUN_DURATION.labels(final_status).observe(max(0, final_duration_ms or 0) / 1000)
    for attempt in state.attempts:
        record_attempt(attempt)


def record_attempt(attempt) -> None:
    failure_stage = attempt.failure_stage or "none"
    recovery_code = attempt.recovery_code or "none"
    ATTEMPTS.labels(attempt.status, failure_stage, recovery_code).inc()
    if attempt.evidence_summary is not None:
        completeness = attempt.evidence_summary.completeness
        evidence_status = "complete" if completeness >= 1 else "incomplete"
        EVIDENCE_COMPLETENESS.labels(evidence_status).observe(completeness)
    if attempt.critic_summary is not None:
        CRITIC_REVIEWS.labels(attempt.critic_summary.severity).inc()
    for call in attempt.tool_calls:
        reused = str(call.reused).lower()
        TOOL_CALLS.labels(call.tool, call.status, reused).inc()
        if not call.reused:
            TOOL_CALL_DURATION.labels(call.tool, call.status).observe(call.latency_ms / 1000)


def record_controller(status: str, failure_code: object | None = None) -> None:
    code = "none" if failure_code is None else normalize_failure_code(failure_code)
    CONTROLLER_CALLS.labels(status, code).inc()


def record_recovery(outcome: str, recovery_code: str) -> None:
    RECOVERY.labels(outcome, recovery_code).inc()


def record_session_operation(
    backend: str,
    operation: str,
    status: str,
    failure_code: object | None = None,
) -> None:
    code = "none" if failure_code is None else normalize_failure_code(failure_code)
    SESSION_OPERATIONS.labels(backend, operation, status, code).inc()


def record_lock_wait(status: str, seconds: float) -> None:
    LOCK_WAIT.labels(status).observe(max(0, seconds))


def record_idempotency(backend: str, action: str) -> None:
    IDEMPOTENCY.labels(backend, action).inc()


def record_chat_run(status: str, duration_seconds: float) -> None:
    """Record a terminal Chat Run without user/session identifiers."""
    CHAT_RUNS.labels(status).inc()
    CHAT_RUN_DURATION.labels(status).observe(max(0, duration_seconds))


def record_chat_run_event(operation: str) -> None:
    CHAT_RUN_EVENTS.labels(operation).inc()


def record_chat_run_event_bus_error(operation: str) -> None:
    CHAT_RUN_EVENT_BUS_ERRORS.labels(operation).inc()


def record_chat_run_cancellation(outcome: str) -> None:
    CHAT_RUN_CANCELLATIONS.labels(outcome).inc()


def record_stale_chat_runs(count: int) -> None:
    if count > 0:
        CHAT_RUN_STALE_INTERRUPTED.inc(count)
