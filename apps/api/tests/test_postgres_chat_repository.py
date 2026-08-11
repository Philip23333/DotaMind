"""PostgreSQL integration coverage for durable anonymous chat sessions."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from app.agentic.conversation.models import Turn
from app.application.chat_repository import (
    ChatFencingLostError,
    ChatIdempotencyConflictError,
    ChatRepositoryError,
)
from app.application.postgres_chat_repository import PostgresChatRepository
from app.persistence.database import close_database, create_database_resources

pytestmark = pytest.mark.skipif(
    not os.getenv("DOTAMIND_TEST_DATABASE_URL"),
    reason="set DOTAMIND_TEST_DATABASE_URL to run PostgreSQL integration tests",
)


def test_postgres_repository_persists_and_isolates_browser_chats() -> None:
    async def scenario() -> None:
        resources = create_database_resources(os.environ["DOTAMIND_TEST_DATABASE_URL"])
        repository = PostgresChatRepository(resources.session_factory)
        browser_a = str(uuid4())
        browser_b = str(uuid4())
        session_id = None
        try:
            created = await repository.create_session(browser_a)
            session_id = created.session_id
            assert created.title == "新对话"
            assert created.is_pinned is False
            assert [item.session_id for item in await repository.list_sessions(browser_a)] == [
                session_id
            ]
            assert await repository.list_sessions(browser_b) == []

            first_token = await repository.claim_fencing(browser_a, session_id, fencing_token=1)
            assert first_token == 1
            request_id = uuid4()
            compact_turn = Turn(query="查一下幻影刺客", response_summary="已完成查询")
            committed = await repository.commit_turn(
                browser_id=browser_a,
                session_id=session_id,
                request_id=request_id,
                payload_hash="payload-a",
                fencing_token=1,
                user_query="查一下幻影刺客",
                assistant_message="已完成查询",
                public_response={"status": "ok", "answer": "结果"},
                compact_turn=compact_turn,
            )
            assert committed.status == "executed"
            assert committed.turn_index == 1

            replay = await repository.lookup_request(
                browser_a, session_id, request_id, payload_hash="payload-a"
            )
            assert replay.status == "replay"
            assert replay.public_response == {"status": "ok", "answer": "结果"}
            with pytest.raises(ChatIdempotencyConflictError):
                await repository.lookup_request(
                    browser_a, session_id, request_id, payload_hash="payload-b"
                )

            snapshot = await repository.get_session(browser_a, session_id)
            assert snapshot.summary.title == "查一下幻影刺客"
            assert len(snapshot.turns) == 1
            assert snapshot.turns[0].turn_index == 1
            assert snapshot.turns[0].user_query == "查一下幻影刺客"
            history = await repository.get_history(browser_a, session_id, limit=10)
            assert history == [compact_turn.model_copy(update={"turn_index": 1})]
            context = await repository.get_conversation_context(browser_a, session_id, limit=10)
            assert context.next_turn_index == 2
            assert [message.role for message in context.recent_messages] == ["user", "assistant"]
            assert context.recent_messages[1].content == "已完成查询"

            recovered_token = await repository.allocate_fencing_token(browser_a, session_id)
            assert recovered_token > first_token
            with pytest.raises(ChatFencingLostError):
                await repository.commit_turn(
                    browser_id=browser_a,
                    session_id=session_id,
                    request_id=uuid4(),
                    payload_hash="stale-owner",
                    fencing_token=first_token,
                    user_query="旧 owner",
                    assistant_message="旧回答",
                    public_response={"status": "ok"},
                    compact_turn=Turn(query="旧 owner"),
                )

            renamed = await repository.rename_session(browser_a, session_id, "幻影刺客分析")
            assert renamed.title == "幻影刺客分析"
            assert renamed.title_is_custom is True

            pinned = await repository.update_session(browser_a, session_id, is_pinned=True)
            assert pinned.is_pinned is True
            assert (await repository.get_session(browser_a, session_id)).summary.is_pinned is True
            unpinned = await repository.update_session(browser_a, session_id, is_pinned=False)
            assert unpinned.is_pinned is False

            with pytest.raises(ChatRepositoryError) as invalid_browser:
                await repository.list_sessions("not-a-uuid")
            assert invalid_browser.value.code == "invalid_browser_id"
        finally:
            if session_id is not None:
                await repository.delete_session(browser_a, session_id)
            await close_database(resources)

    asyncio.run(scenario())
