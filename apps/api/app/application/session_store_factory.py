"""Build the configured SessionStore without leaking backend choices to callers."""

from __future__ import annotations

from app.application.redis_session_store import RedisSessionStore
from app.application.session_store import InMemorySessionStore, SessionStore
from app.core.config import AppPolicy, Settings


def build_session_store(settings: Settings, policy: AppPolicy) -> SessionStore:
    conversation = policy.conversation
    common = {
        "max_turns_per_session": conversation.max_turns_per_session,
        "request_record_ttl_seconds": conversation.request_record_ttl_seconds,
        "max_request_records_per_session": conversation.max_request_records_per_session,
    }
    if settings.session_store_backend == "memory":
        return InMemorySessionStore(
            max_sessions=conversation.max_sessions,
            **common,
        )
    if settings.redis_url is None:  # Settings validation normally rejects this.
        raise RuntimeError("DOTAMIND_REDIS_URL is required for redis session storage")
    return RedisSessionStore(
        redis_url=settings.redis_url,
        session_ttl_seconds=conversation.session_ttl_seconds,
        lock_lease_seconds=conversation.lock_lease_seconds,
        lock_acquire_timeout_seconds=conversation.lock_acquire_timeout_seconds,
        **common,
    )
