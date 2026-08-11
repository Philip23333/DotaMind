"""Short-lived recent dialogue cache backed by authoritative PostgreSQL turns."""

from __future__ import annotations

from uuid import UUID

from app.agentic.conversation.models import ConversationMessage, DialogueTurn, RecentDialogueWindow
from app.application.postgres_chat_repository import PostgresChatRepository
from app.application.session_store import SessionStore, SessionStoreError

_TRUNCATION_MARKER = "\n[内容已截断]"


def _truncate(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(_TRUNCATION_MARKER):
        return _TRUNCATION_MARKER[:limit]
    return text[: limit - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER


def build_recent_dialogue_window(
    turns: list[DialogueTurn],
    *,
    max_chars: int,
) -> RecentDialogueWindow:
    """Keep complete newest turns under the budget and mark omitted history."""

    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    ordered = sorted(turns, key=lambda item: item.turn_index)
    kept: list[DialogueTurn] = []
    used = 0
    for turn in reversed(ordered):
        cost = len(turn.user_message) + len(turn.assistant_message)
        if kept and used + cost > max_chars:
            break
        if not kept and cost > max_chars:
            user_budget = min(len(turn.user_message), max(1, max_chars // 3))
            assistant_budget = max(1, max_chars - user_budget)
            kept.append(
                DialogueTurn(
                    turn_index=turn.turn_index,
                    user_message=_truncate(turn.user_message, user_budget),
                    assistant_message=_truncate(turn.assistant_message, assistant_budget),
                )
            )
            used = max_chars
            break
        kept.append(turn)
        used += cost

    kept.reverse()
    through = kept[-1].turn_index if kept else 0
    return RecentDialogueWindow(
        through_turn_index=through,
        truncated_before=len(kept) < len(ordered),
        turns=kept,
    )


def messages_from_window(window: RecentDialogueWindow) -> list[ConversationMessage]:
    return [
        message
        for turn in window.turns
        for message in (
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
        )
    ]


class ConversationMemoryService:
    """Coordinate the Redis recent window and PostgreSQL dialogue source."""

    def __init__(
        self,
        *,
        chat_repository: PostgresChatRepository,
        session_store: SessionStore,
        max_chars: int = 24_000,
    ) -> None:
        self._chat_repository = chat_repository
        self._session_store = session_store
        self._max_chars = max_chars

    async def load_recent_messages(
        self,
        browser_id: str,
        session_id: UUID,
    ) -> tuple[list[ConversationMessage], int]:
        try:
            cached = await self._session_store.get_recent_dialogue(str(session_id))
        except SessionStoreError:
            cached = None
        next_turn_index = await self._chat_repository.get_next_turn_index(
            browser_id, session_id
        )
        if cached is None or cached.through_turn_index != next_turn_index - 1:
            all_turns, next_turn_index = await self._chat_repository.get_all_dialogue_turns(
                browser_id, session_id
            )
            cached = build_recent_dialogue_window(all_turns, max_chars=self._max_chars)
            try:
                await self._session_store.replace_recent_dialogue(str(session_id), cached)
            except SessionStoreError:
                pass
        return messages_from_window(cached), next_turn_index

    async def record_committed_turn(
        self,
        browser_id: str,
        session_id: UUID,
        turn: DialogueTurn,
    ) -> None:
        try:
            cached = await self._session_store.get_recent_dialogue(str(session_id))
        except SessionStoreError:
            # The cache state is unknown.  Do not read PostgreSQL again after
            # the durable commit; let the next request perform cache-aside
            # reconstruction after this infrastructure failure is surfaced.
            raise
        if cached is None:
            if turn.turn_index == 1:
                window = build_recent_dialogue_window([turn], max_chars=self._max_chars)
                await self._session_store.replace_recent_dialogue(str(session_id), window)
                return
            await self._session_store.invalidate_recent_dialogue(str(session_id))
            return
        if cached.through_turn_index != turn.turn_index - 1:
            await self._session_store.invalidate_recent_dialogue(str(session_id))
            return
        window = build_recent_dialogue_window(
            [*cached.turns, turn], max_chars=self._max_chars
        )
        await self._session_store.replace_recent_dialogue(str(session_id), window)


__all__ = [
    "ConversationMemoryService",
    "build_recent_dialogue_window",
    "messages_from_window",
]
