"""Build compact audit records and complete assistant messages."""

from __future__ import annotations

from app.agentic.conversation.models import Turn

SESSION_REQUEST_FAILED_REASON = "The session request could not be completed safely."


def render_assistant_message(state: object) -> str:
    """Return the complete assistant text that was shown for a run."""

    if getattr(state, "safe_failure_required", False):
        return SESSION_REQUEST_FAILED_REASON
    answer = getattr(state, "answer", None)
    if answer is not None:
        summary = getattr(answer, "summary", None)
        if summary:
            return str(summary)
    decision = getattr(state, "decision", None)
    if decision is not None:
        question = getattr(decision, "question", None)
        if question:
            return str(question)
        reason = getattr(decision, "reason", None)
        if reason:
            return str(reason)
    return str(getattr(state, "reason", "") or "")


def build_turn_summary(
    state: object,
    *,
    max_summary_chars: int = 300,
    max_query_chars: int = 200,
) -> Turn:
    """Build a bounded audit summary from a completed AgentRunState."""

    query = _safe_str(getattr(state, "query", ""), max_query_chars)
    status = getattr(state, "status", "error")
    response_type = getattr(state, "response_type", None)
    decision = getattr(state, "decision", None)
    plan = getattr(state, "plan", None)
    intent = getattr(plan, "intent", None) if plan is not None else (
        getattr(decision, "intent", None) if decision is not None else None
    )
    context_scope: dict = {}
    if plan is not None:
        context = getattr(plan, "context", None)
        if context is not None:
            try:
                context_scope = context.model_dump(mode="json", exclude_none=True)
            except Exception:
                context_scope = {}

    return Turn(
        turn_index=0,
        query=query,
        status=status,  # type: ignore[arg-type]
        response_type=response_type,
        intent=intent,
        context_scope=context_scope,
        missing_fields=list(getattr(decision, "missing_fields", []) or []),
        response_summary=_safe_str(render_assistant_message(state), max_summary_chars),
    )


def build_session_failure_turn(
    state: object,
    *,
    max_query_chars: int = 200,
) -> Turn:
    """Build the redacted audit record for a safely hidden runtime failure."""

    return Turn(
        turn_index=0,
        query=_safe_str(getattr(state, "query", ""), max_query_chars),
        status=getattr(state, "status", "error"),  # type: ignore[arg-type]
        response_type="session_request_failed",
        response_summary=SESSION_REQUEST_FAILED_REASON,
    )


def _safe_str(value: str, max_chars: int) -> str:
    return value[:max_chars] if value else ""


__all__ = [
    "SESSION_REQUEST_FAILED_REASON",
    "build_session_failure_turn",
    "build_turn_summary",
    "render_assistant_message",
]
