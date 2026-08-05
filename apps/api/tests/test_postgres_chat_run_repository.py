"""PostgreSQL integration coverage for durable chat Run lifecycle state."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.application.chat_run_repository import (
    ChatRunActiveError,
    ChatRunIdempotencyConflictError,
    ChatRunNotFoundError,
    ChatRunStateError,
    ChatRunTerminalError,
)
from app.application.postgres_chat_repository import PostgresChatRepository
from app.application.postgres_chat_run_repository import PostgresChatRunRepository
from app.persistence.database import close_database, create_database_resources

pytestmark = pytest.mark.skipif(
    not os.getenv("DOTAMIND_TEST_DATABASE_URL"),
    reason="set DOTAMIND_TEST_DATABASE_URL to run PostgreSQL integration tests",
)


def test_postgres_run_repository_enforces_lifecycle_and_ownership() -> None:
    async def scenario() -> None:
        resources = create_database_resources(os.environ["DOTAMIND_TEST_DATABASE_URL"])
        chats = PostgresChatRepository(resources.session_factory)
        runs = PostgresChatRunRepository(resources.session_factory)
        browser_a = str(uuid4())
        browser_b = str(uuid4())
        session_id = None
        second_session_id = None
        try:
            created_session = await chats.create_session(browser_a)
            session_id = created_session.session_id
            second_session_id = (await chats.create_session(browser_a)).session_id
            request_id = uuid4()
            run_id = uuid4()

            created = await runs.create_or_get_run(
                browser_id=browser_a,
                session_id=session_id,
                request_id=request_id,
                payload_hash="payload-a",
                user_query="分析幻影刺客",
                run_id=run_id,
            )
            assert created.action == "created"
            assert created.run.run_id == run_id
            assert created.run.status == "queued"

            replay = await runs.create_or_get_run(
                browser_id=browser_a,
                session_id=session_id,
                request_id=request_id,
                payload_hash="payload-a",
                user_query="分析幻影刺客",
                run_id=uuid4(),
            )
            assert replay.action == "replayed"
            assert replay.run.run_id == run_id

            with pytest.raises(ChatRunIdempotencyConflictError):
                await runs.create_or_get_run(
                    browser_id=browser_a,
                    session_id=session_id,
                    request_id=request_id,
                    payload_hash="payload-b",
                    user_query="不同问题",
                    run_id=uuid4(),
                )

            with pytest.raises(ChatRunNotFoundError):
                await runs.get_run_for_browser(browser_b, run_id)

            started = await runs.mark_running(
                browser_id=browser_a,
                run_id=run_id,
                worker_id="worker-a",
                fencing_token=1,
            )
            assert started.status == "running"
            assert started.worker_id == "worker-a"
            assert started.fencing_token == 1

            with pytest.raises(ChatRunActiveError):
                await runs.create_or_get_run(
                    browser_id=browser_a,
                    session_id=session_id,
                    request_id=uuid4(),
                    payload_hash="payload-c",
                    user_query="并发问题",
                    run_id=uuid4(),
                )

            heartbeat = await runs.update_heartbeat(run_id=run_id, worker_id="worker-a")
            assert heartbeat.heartbeat_at is not None

            cancelled = await runs.request_cancel(browser_id=browser_a, run_id=run_id)
            assert cancelled.action == "requested"
            assert cancelled.run.status == "cancel_requested"
            with pytest.raises(ChatRunStateError):
                await runs.mark_running(
                    browser_id=browser_a,
                    run_id=run_id,
                    worker_id="worker-a",
                    fencing_token=1,
                )
            finished = await runs.mark_cancelled(run_id=run_id, worker_id="worker-a")
            assert finished.run_id == run_id
            assert finished.status == "cancelled"
            with pytest.raises(ChatRunTerminalError):
                await runs.request_cancel(browser_id=browser_a, run_id=run_id)

            other_run = await runs.create_or_get_run(
                browser_id=browser_a,
                session_id=second_session_id,
                request_id=uuid4(),
                payload_hash="payload-d",
                user_query="另一个聊天",
                run_id=uuid4(),
            )
            assert other_run.run.status == "queued"
            stale = await runs.interrupt_stale_runs(
                stale_before=datetime.now(UTC) + timedelta(seconds=1),
                error_code="worker_stale",
            )
            assert other_run.run_id in stale
        finally:
            if session_id is not None:
                await chats.delete_session(browser_a, session_id)
            if second_session_id is not None:
                await chats.delete_session(browser_a, second_session_id)
            await close_database(resources)

    asyncio.run(scenario())
