"""Request-local context for the internal conversation history tool."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID

from app.agentic.conversation.models import ConversationMessage
from app.application.postgres_chat_repository import PostgresChatRepository


@dataclass(frozen=True)
class HistoryLookupContext:
    chat_repository: PostgresChatRepository
    browser_id: str
    session_id: UUID
    max_turns: int = 8
    max_chars: int = 12_000


_CURRENT: ContextVar[HistoryLookupContext | None] = ContextVar(
    "dotamind_history_lookup_context", default=None
)


@contextmanager
def bind_history_lookup_context(context: HistoryLookupContext):
    token: Token[HistoryLookupContext | None] = _CURRENT.set(context)
    try:
        yield
    finally:
        _CURRENT.reset(token)


async def lookup_history(
    *,
    query_text: str | None = None,
    turn_indexes: list[int] | None = None,
    before_turn_index: int | None = None,
    limit: int = 8,
) -> dict[str, object]:
    context = _CURRENT.get()
    if context is None:
        raise RuntimeError("history lookup is only available during a chat run")
    turns = await context.chat_repository.lookup_dialogue(
        context.browser_id,
        context.session_id,
        turn_indexes=turn_indexes,
        before_turn_index=before_turn_index,
        query_text=query_text,
        limit=min(limit, context.max_turns),
    )
    messages: list[ConversationMessage] = []
    used = 0
    for turn in turns:
        candidate = [
            ConversationMessage(
                turn_index=turn.turn_index,
                role="user",
                content=turn.user_message,
            ),
            ConversationMessage(
                turn_index=turn.turn_index,
                role="assistant",
                content=turn.assistant_message,
            ),
        ]
        cost = sum(len(message.content) for message in candidate)
        if messages and used + cost > context.max_chars:
            break
        messages.extend(candidate)
        used += cost
    return {
        "status": "ok",
        "messages": [message.model_dump(mode="json") for message in messages],
        "turn_indexes": sorted({message.turn_index for message in messages}),
    }


__all__ = ["HistoryLookupContext", "bind_history_lookup_context", "lookup_history"]
