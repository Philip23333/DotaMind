"""Real PostgreSQL/Redis recovery tests for the V3.3 fencing boundary."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.agentic.conversation.models import Turn
from app.application.postgres_chat_repository import PostgresChatRepository
from app.application.redis_session_store import RedisSessionStore
from app.application.session_store import SessionStoreError
from app.persistence.database import close_database, create_database_resources

pytestmark = pytest.mark.skipif(
    not os.getenv("DOTAMIND_TEST_DATABASE_URL")
    or not os.getenv("DOTAMIND_TEST_REDIS_URL"),
    reason="PostgreSQL and Redis integration URLs are required",
)


def test_postgres_fencing_recovers_after_redis_state_loss_and_expiry() -> None:
    async def scenario() -> None:
        database = create_database_resources(os.environ["DOTAMIND_TEST_DATABASE_URL"])
        redis = Redis.from_url(os.environ["DOTAMIND_TEST_REDIS_URL"], decode_responses=True)
        prefix = f"dotamind:test:fencing:{uuid4()}"
        store = RedisSessionStore(
            redis=redis,
            key_prefix=prefix,
            lock_lease_seconds=3,
            lock_acquire_timeout_seconds=3,
            session_ttl_seconds=1,
        )
        repository = PostgresChatRepository(database.session_factory)
        browser_id = str(uuid4())
        session_id = None
        try:
            await redis.ping()
            created = await repository.create_session(browser_id)
            session_id = created.session_id

            async with store.transaction(str(session_id)):
                token_one = await repository.allocate_fencing_token(browser_id, session_id)
                await repository.commit_turn(
                    browser_id=browser_id,
                    session_id=session_id,
                    request_id=uuid4(),
                    payload_hash="one",
                    fencing_token=token_one,
                    user_query="第一轮",
                    public_response={"status": "ok", "answer": "一"},
                    compact_turn=Turn(query="第一轮"),
                )

            # Simulate a Redis session-key flush without touching PostgreSQL.
            await store.delete_session(str(session_id))
            async with store.transaction(str(session_id)):
                token_two = await repository.allocate_fencing_token(browser_id, session_id)
            assert token_two > token_one

            # Let the recreated Redis metadata expire naturally. PostgreSQL's
            # counter must still provide the next strictly larger token.
            await asyncio.sleep(1.3)
            async with store.transaction(str(session_id)):
                token_three = await repository.allocate_fencing_token(browser_id, session_id)
            assert token_three > token_two
        finally:
            if session_id is not None:
                await repository.delete_session(browser_id, session_id)
                await store.delete_session(str(session_id))
            await store.aclose()
            await redis.aclose()
            await close_database(database)

    asyncio.run(scenario())


def test_redis_delete_does_not_remove_another_owner_lock() -> None:
    async def scenario() -> None:
        redis = Redis.from_url(os.environ["DOTAMIND_TEST_REDIS_URL"], decode_responses=True)
        prefix = f"dotamind:test:delete-lock:{uuid4()}"
        first = RedisSessionStore(
            redis=redis,
            key_prefix=prefix,
            lock_lease_seconds=3,
            lock_acquire_timeout_seconds=0.2,
        )
        second = RedisSessionStore(
            redis=redis,
            key_prefix=prefix,
            lock_lease_seconds=3,
            lock_acquire_timeout_seconds=0.2,
        )
        session_id = str(uuid4())
        try:
            await redis.ping()
            async with first.transaction(session_id):
                delete_task = asyncio.create_task(second.delete_session(session_id))
                with pytest.raises(SessionStoreError, match="lock_timeout"):
                    await delete_task
                assert await redis.exists(first._keys(session_id)["lock"]) == 1
        finally:
            await first.delete_session(session_id)
            await first.aclose()
            await second.aclose()
            await redis.aclose()

    asyncio.run(scenario())
