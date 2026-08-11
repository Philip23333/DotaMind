import asyncio
from uuid import UUID, uuid4

import pytest

from app.agentic.conversation.models import ConversationMessage, DialogueTurn, RecentDialogueWindow
from app.application.conversation_memory import (
    ConversationMemoryService,
    build_recent_dialogue_window,
    messages_from_window,
)
from app.application.session_store import SessionStoreError


def _turn(index: int, user: str, assistant: str) -> DialogueTurn:
    return DialogueTurn(turn_index=index, user_message=user, assistant_message=assistant)


def test_recent_window_keeps_complete_newest_turns_and_marks_older_history() -> None:
    window = build_recent_dialogue_window(
        [_turn(1, "old user", "old answer"), _turn(2, "new user", "new answer")],
        max_chars=len("new user") + len("new answer"),
    )

    assert [turn.turn_index for turn in window.turns] == [2]
    assert window.through_turn_index == 2
    assert window.truncated_before is True


def test_recent_window_truncates_the_latest_turn_deterministically() -> None:
    window = build_recent_dialogue_window(
        [_turn(1, "u" * 40, "a" * 40)],
        max_chars=20,
    )

    assert window.through_turn_index == 1
    assert window.truncated_before is False
    assert len(window.turns[0].user_message) + len(window.turns[0].assistant_message) <= 20
    assert "内容已截断" in window.turns[0].assistant_message


def test_window_messages_are_real_alternating_roles() -> None:
    window = RecentDialogueWindow(
        through_turn_index=2,
        turns=[_turn(2, "用户问题", "助手回答")],
    )

    assert messages_from_window(window) == [
        ConversationMessage(turn_index=2, role="user", content="用户问题"),
        ConversationMessage(turn_index=2, role="assistant", content="助手回答"),
    ]


class _Store:
    def __init__(self, window=None) -> None:
        self.window = window
        self.replacements = 0
        self.invalidations = 0

    async def get_recent_dialogue(self, session_id: str):
        return self.window

    async def replace_recent_dialogue(self, session_id: str, window):
        self.window = window
        self.replacements += 1

    async def invalidate_recent_dialogue(self, session_id: str):
        self.window = None
        self.invalidations += 1


class _Repository:
    def __init__(self, turns: list[DialogueTurn]) -> None:
        self.turns = turns
        self.next_turn_index_calls = 0
        self.full_history_calls = 0

    async def get_next_turn_index(self, browser_id: str, session_id: UUID) -> int:
        self.next_turn_index_calls += 1
        return (self.turns[-1].turn_index + 1) if self.turns else 1

    async def get_all_dialogue_turns(self, browser_id: str, session_id: UUID):
        self.full_history_calls += 1
        return self.turns, (self.turns[-1].turn_index + 1) if self.turns else 1


def test_memory_service_rebuilds_on_miss_and_uses_cache_afterward() -> None:
    async def scenario() -> None:
        turns = [_turn(1, "q", "a")]
        store = _Store()
        repository = _Repository(turns)
        service = ConversationMemoryService(
            chat_repository=repository, session_store=store, max_chars=100
        )
        session_id = uuid4()

        first = await service.load_recent_messages("browser", session_id)
        second = await service.load_recent_messages("browser", session_id)

        assert first[1] == second[1] == 2
        assert first[0][0].role == "user"
        assert repository.full_history_calls == 1
        assert store.replacements == 1

    asyncio.run(scenario())


def test_record_committed_turn_appends_contiguous_cache_without_postgres_read() -> None:
    async def scenario() -> None:
        store = _Store(
            RecentDialogueWindow(
                through_turn_index=1,
                turns=[_turn(1, "q1", "a1")],
            )
        )
        repository = _Repository([_turn(1, "q1", "a1")])
        service = ConversationMemoryService(
            chat_repository=repository, session_store=store, max_chars=100
        )

        await service.record_committed_turn(
            "browser", uuid4(), _turn(2, "q2", "a2")
        )

        assert store.invalidations == 0
        assert store.window is not None
        assert [turn.turn_index for turn in store.window.turns] == [1, 2]
        assert repository.full_history_calls == 0

    asyncio.run(scenario())


def test_record_committed_turn_invalidates_gap_without_reloading_postgres() -> None:
    async def scenario() -> None:
        store = _Store()
        repository = _Repository([_turn(1, "q1", "a1"), _turn(2, "q2", "a2")])
        service = ConversationMemoryService(
            chat_repository=repository, session_store=store, max_chars=100
        )

        await service.record_committed_turn(
            "browser", uuid4(), _turn(3, "q3", "a3")
        )

        assert store.invalidations == 1
        assert store.replacements == 0
        assert repository.full_history_calls == 0

    asyncio.run(scenario())


def test_record_committed_turn_surfaces_cache_get_failure() -> None:
    class FailingGetStore(_Store):
        async def get_recent_dialogue(self, session_id: str):
            raise SessionStoreError("unavailable")

    async def scenario() -> None:
        store = FailingGetStore()
        repository = _Repository([])
        service = ConversationMemoryService(
            chat_repository=repository, session_store=store, max_chars=100
        )

        with pytest.raises(SessionStoreError, match="unavailable"):
            await service.record_committed_turn(
                "browser", uuid4(), _turn(1, "q1", "a1")
            )
        assert repository.full_history_calls == 0

    asyncio.run(scenario())
