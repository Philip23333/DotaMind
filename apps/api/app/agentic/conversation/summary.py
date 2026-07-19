"""Extract a compact Turn summary from a completed AgentRunState.

The summary is intentionally lossy: only the fields the Controller needs for
pronoun resolution and context inheritance are preserved.  Full tool results,
evidence, traces, and raw Controller messages are NOT stored.
"""

from __future__ import annotations

from app.agentic.conversation.models import ResolvedEntity, Turn

SESSION_REQUEST_FAILED_REASON = "The session request could not be completed safely."

# Evidence kinds that represent resolvable game entities.
# tuple: (entity_type, name_value_key_or_None, id_value_key)
# When name_value_key is None, item.subject is used as the name.
_ENTITY_EVIDENCE_KINDS: dict[str, tuple[str, str | None, str]] = {
    "hero_identity": ("hero", "localized_name", "hero_id"),
    "team_identity": ("team", None, "team_id"),
    "player_identity": ("player", None, "steam_account_id"),
}


def build_turn_summary(
    state: object,
    *,
    max_summary_chars: int = 300,
    max_query_chars: int = 200,
) -> Turn:
    """Build a Turn from a completed AgentRunState.

    Uses ``object`` type hint to avoid importing AgentRunState here (which
    would create a cross-layer import); callers pass an AgentRunState instance.
    All attribute accesses are guarded so a partial/error state never raises.
    """
    query = _safe_str(getattr(state, "query", ""), max_query_chars)
    status = getattr(state, "status", "error")
    response_type = getattr(state, "response_type", None)

    decision = getattr(state, "decision", None)

    plan = getattr(state, "plan", None)
    if plan is not None:
        intent: str | None = getattr(plan, "intent", None)
    else:
        intent = getattr(decision, "intent", None) if decision is not None else None
    context_scope: dict = {}
    if plan is not None:
        ctx = getattr(plan, "context", None)
        if ctx is not None:
            try:
                context_scope = ctx.model_dump(mode="json", exclude_none=True)
            except Exception:
                context_scope = {}

    answer = getattr(state, "answer", None)
    if answer is not None and getattr(answer, "summary", None):
        response_summary = _safe_str(answer.summary, max_summary_chars)
    elif decision is not None and getattr(decision, "question", None):
        response_summary = _safe_str(decision.question, max_summary_chars)
    elif decision is not None and getattr(decision, "reason", None):
        response_summary = _safe_str(decision.reason, max_summary_chars)
    else:
        response_summary = _safe_str(getattr(state, "reason", "") or "", max_summary_chars)

    resolved_entities: list[ResolvedEntity] = []
    evidence_graph = getattr(state, "evidence_graph", None)
    if evidence_graph is not None:
        for item in getattr(evidence_graph, "evidence", []):
            kind = getattr(item, "kind", "")
            if kind not in _ENTITY_EVIDENCE_KINDS:
                continue
            entity_type, name_key, id_key = _ENTITY_EVIDENCE_KINDS[kind]
            value: dict = getattr(item, "value", {}) or {}
            subject: str = getattr(item, "subject", "") or ""
            name = str(value.get(name_key) or subject) if name_key else subject
            id_ = value.get(id_key)
            resolved_entities.append(
                ResolvedEntity(type=entity_type, name=name, id=id_)  # type: ignore[arg-type]
            )

    return Turn(
        # turn_index is placeholder 0; SessionStore.append() assigns the real index.
        turn_index=0,
        query=query,
        status=status,  # type: ignore[arg-type]
        response_type=response_type,
        intent=intent,
        resolved_entities=resolved_entities,
        context_scope=context_scope,
        missing_fields=list(getattr(decision, "missing_fields", []) or []),
        response_summary=response_summary,
    )


def build_session_failure_turn(
    state: object,
    *,
    max_query_chars: int = 200,
) -> Turn:
    """Build the only session record allowed for a redacted public failure.

    Controller errors can contain untrusted model text, rejected plans, or a
    Pydantic echo of historical input.  None of that may become future session
    context, so this deliberately ignores every field except the current query
    and coarse status.
    """
    return Turn(
        turn_index=0,
        query=_safe_str(getattr(state, "query", ""), max_query_chars),
        status=getattr(state, "status", "error"),  # type: ignore[arg-type]
        response_type="session_request_failed",
        response_summary=SESSION_REQUEST_FAILED_REASON,
    )


def _safe_str(value: str, max_chars: int) -> str:
    return value[:max_chars] if value else ""
