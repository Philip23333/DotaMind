"""Real-Redis integration tests for V3.2-5.

Set DOTAMIND_TEST_REDIS_URL to run these tests. CI must provide a real Redis
instance; local unit runs may skip only this integration module.
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.agentic.conversation.models import Turn
from app.api.v1.schemas import PlanResponse
from app.application.redis_session_store import (
    _RENEW_LUA,
    RedisSessionStore,
)
from app.application.session_store import SessionStoreError

pytestmark = pytest.mark.skipif(
    not os.getenv("DOTAMIND_TEST_REDIS_URL"),
    reason="DOTAMIND_TEST_REDIS_URL is required for real Redis integration tests",
)


@dataclass
class RedisHarness:
    url: str
    prefix: str = field(default_factory=lambda: f"dotamind:test:{uuid4()}")
    sessions: set[str] = field(default_factory=set)
    client: Redis | None = None

    async def open(self) -> None:
        self.client = Redis.from_url(self.url, decode_responses=True)
        await self.client.ping()

    def session(self) -> str:
        session_id = str(uuid4())
        self.sessions.add(session_id)
        return session_id

    def store(self, **overrides) -> RedisSessionStore:
        assert self.client is not None
        options = {
            "redis": self.client,
            "key_prefix": self.prefix,
            "lock_lease_seconds": 3,
            "lock_acquire_timeout_seconds": 3,
            "session_ttl_seconds": 120,
            "request_record_ttl_seconds": 60,
        }
        options.update(overrides)
        return RedisSessionStore(**options)

    async def corrupt_request_record(
        self,
        store: RedisSessionStore,
        session_id: str,
        request_id,
    ) -> None:
        assert self.client is not None
        keys = store._keys(session_id)
        request_key = store.request_key_hash(request_id)
        raw = await self.client.hget(keys["requests"], request_key)
        assert raw is not None
        payload = json.loads(raw)
        payload["schema_version"] = 2
        await self.client.hset(keys["requests"], request_key, json.dumps(payload))

    async def close(self) -> None:
        assert self.client is not None
        keys: list[str] = []
        for session_id in self.sessions:
            keys.extend(self.store()._keys(session_id).values())
        if keys:
            await self.client.delete(*keys)
        await self.client.aclose()


def _public_response(run_id) -> dict:
    return {
        "query": "q",
        "game": "dota2",
        "status": "ok",
        "reason": "done",
        "missing_fields": [],
        "planner_required_evidence": [],
        "effective_required_evidence": [],
        "required_evidence_sources": {},
        "tool_results": [],
        "errors": [],
        "trace": [],
        "runtime": {
            "run_id": str(run_id),
            "duration_ms": 0,
            "terminal_stage": "answer",
            "budget": {
                "limits": {
                    "max_replans": 1,
                    "max_tool_calls_total": 1,
                    "max_controller_calls": 1,
                    "max_answer_calls": 1,
                    "max_elapsed_seconds": 1,
                },
                "used": {
                    "replans_used": 0,
                    "tool_calls_used": 0,
                    "controller_calls_used": 0,
                    "answer_calls_used": 0,
                },
            },
            "attempts": [],
        },
    }


def _run(coro):
    return asyncio.run(coro)


def test_replay_preserves_public_response_empty_arrays() -> None:
    harness = RedisHarness(os.environ["DOTAMIND_TEST_REDIS_URL"])
    request_id, run_id = uuid4(), uuid4()
    public_response = _public_response(run_id)

    async def scenario():
        await harness.open()
        store = harness.store()
        session_id = harness.session()
        async with store.transaction(session_id):
            claim = await store.begin_request(session_id, request_id, "payload")
            assert claim.owner_token is not None
            await store.complete_request_with_turn(
                session_id,
                request_id,
                claim.owner_token,
                Turn(query="q"),
                public_response,
                run_id,
            )
        async with store.transaction(session_id):
            replay = await store.begin_request(session_id, request_id, "payload")
        await harness.close()
        return replay

    replay = _run(scenario())

    assert replay.action == "replay"
    assert replay.cached_public_response == public_response
    assert PlanResponse.model_validate(replay.cached_public_response)


def test_completed_request_replays_when_request_capacity_is_full() -> None:
    harness = RedisHarness(os.environ["DOTAMIND_TEST_REDIS_URL"])
    request_id, run_id = uuid4(), uuid4()

    async def scenario():
        await harness.open()
        store = harness.store(max_request_records_per_session=1)
        session_id = harness.session()
        async with store.transaction(session_id):
            claim = await store.begin_request(session_id, request_id, "payload")
            assert claim.owner_token is not None
            await store.complete_request_with_turn(
                session_id,
                request_id,
                claim.owner_token,
                Turn(query="q"),
                _public_response(run_id),
                run_id,
            )
        async with store.transaction(session_id):
            replay = await store.begin_request(session_id, request_id, "payload")
        await harness.close()
        return replay

    assert _run(scenario()).action == "replay"


def test_active_transaction_renews_before_short_session_ttl_expires() -> None:
    harness = RedisHarness(os.environ["DOTAMIND_TEST_REDIS_URL"])

    async def scenario():
        await harness.open()
        store = harness.store(session_ttl_seconds=1, lock_lease_seconds=3)
        session_id = harness.session()
        async with store.transaction(session_id):
            first = await store.append(session_id, Turn(query="first"))
            await asyncio.sleep(1.2)
            history = await store.get(session_id, limit=5)
            second = await store.append(session_id, Turn(query="second"))
        await harness.close()
        return first, history, second

    first, history, second = _run(scenario())

    assert first.turn_index == 1
    assert [turn.query for turn in history] == ["first"]
    assert second.turn_index == 2


def test_begin_request_rejects_unknown_request_record_schema() -> None:
    harness = RedisHarness(os.environ["DOTAMIND_TEST_REDIS_URL"])
    request_id = uuid4()

    async def scenario():
        await harness.open()
        store = harness.store()
        session_id = harness.session()
        async with store.transaction(session_id):
            await store.begin_request(session_id, request_id, "payload")
            await harness.corrupt_request_record(store, session_id, request_id)
        async with store.transaction(session_id):
            with pytest.raises(SessionStoreError, match="data_invalid"):
                await store.begin_request(session_id, request_id, "payload")
        await harness.close()

    _run(scenario())


def test_complete_rejects_unknown_request_record_schema_without_turn() -> None:
    harness = RedisHarness(os.environ["DOTAMIND_TEST_REDIS_URL"])
    request_id, run_id = uuid4(), uuid4()

    async def scenario():
        await harness.open()
        store = harness.store()
        session_id = harness.session()
        async with store.transaction(session_id):
            claim = await store.begin_request(session_id, request_id, "payload")
            assert claim.owner_token is not None
            await harness.corrupt_request_record(store, session_id, request_id)
            with pytest.raises(SessionStoreError, match="data_invalid"):
                await store.complete_request_with_turn(
                    session_id,
                    request_id,
                    claim.owner_token,
                    Turn(query="q"),
                    _public_response(run_id),
                    run_id,
                )
        turns = await store.get(session_id, limit=5)
        await harness.close()
        return turns

    assert _run(scenario()) == []


def test_fail_rejects_unknown_request_record_schema() -> None:
    harness = RedisHarness(os.environ["DOTAMIND_TEST_REDIS_URL"])
    request_id = uuid4()

    async def scenario():
        await harness.open()
        store = harness.store()
        session_id = harness.session()
        async with store.transaction(session_id):
            claim = await store.begin_request(session_id, request_id, "payload")
            assert claim.owner_token is not None
            await harness.corrupt_request_record(store, session_id, request_id)
            with pytest.raises(SessionStoreError, match="data_invalid"):
                await store.fail_request(session_id, request_id, claim.owner_token)
        await harness.close()

    _run(scenario())


def test_two_stores_preserve_turn_order_and_fencing() -> None:
    harness = RedisHarness(os.environ["DOTAMIND_TEST_REDIS_URL"])

    async def scenario():
        await harness.open()
        first, second = harness.store(), harness.store()
        session_id = harness.session()
        async with first.transaction(session_id):
            first_context = first._require_context(session_id)
            stored_one = await first.append(session_id, Turn(query="one"))
        async with second.transaction(session_id):
            second_context = second._require_context(session_id)
            stored_two = await second.append(session_id, Turn(query="two"))
        turns = await first.get(session_id, limit=10)
        await harness.close()
        return first_context, second_context, stored_one, stored_two, turns

    first_context, second_context, stored_one, stored_two, turns = _run(scenario())

    assert second_context.fencing_token > first_context.fencing_token
    assert [stored_one.turn_index, stored_two.turn_index] == [1, 2]
    assert [turn.turn_index for turn in turns] == [1, 2]


def test_turn_index_replacement_does_not_touch_nested_context_fields() -> None:
    harness = RedisHarness(os.environ["DOTAMIND_TEST_REDIS_URL"])
    request_id, run_id = uuid4(), uuid4()

    async def scenario():
        await harness.open()
        store = harness.store()
        session_id = harness.session()
        async with store.transaction(session_id):
            appended = await store.append(
                session_id,
                Turn(query="append", context_scope={"turn_index": 99}),
            )
            claim = await store.begin_request(session_id, request_id, "payload")
            assert claim.owner_token is not None
            completed = await store.complete_request_with_turn(
                session_id,
                request_id,
                claim.owner_token,
                Turn(query="complete", context_scope={"turn_index": 123}),
                _public_response(run_id),
                run_id,
            )
        turns = await store.get(session_id, limit=10)
        await harness.close()
        return appended, completed, turns

    appended, completed, turns = _run(scenario())

    assert appended.turn_index == 1
    assert appended.context_scope == {"turn_index": 99}
    assert completed.turn_index == 2
    assert completed.context_scope == {"turn_index": 123}
    assert [turn.turn_index for turn in turns] == [1, 2]


def test_failed_request_is_taken_over_and_completed_once() -> None:
    harness = RedisHarness(os.environ["DOTAMIND_TEST_REDIS_URL"])
    request_id, run_id = uuid4(), uuid4()

    async def scenario():
        await harness.open()
        first, second = harness.store(), harness.store()
        session_id = harness.session()
        async with first.transaction(session_id):
            original = await first.begin_request(session_id, request_id, "payload")
            assert original.owner_token is not None
            await first.fail_request(session_id, request_id, original.owner_token)
        async with second.transaction(session_id):
            takeover = await second.begin_request(session_id, request_id, "payload")
            assert takeover.owner_token is not None
            assert takeover.owner_token != original.owner_token
            await second.complete_request_with_turn(
                session_id,
                request_id,
                takeover.owner_token,
                Turn(query="taken over"),
                _public_response(run_id),
                run_id,
            )
        async with first.transaction(session_id):
            replay = await first.begin_request(session_id, request_id, "payload")
        turns = await first.get(session_id, limit=10)
        await harness.close()
        return replay, turns

    replay, turns = _run(scenario())

    assert replay.action == "replay"
    assert [turn.query for turn in turns] == ["taken over"]
    assert [turn.turn_index for turn in turns] == [1]


def test_redis_serializes_same_session_and_allows_different_sessions() -> None:
    harness = RedisHarness(os.environ["DOTAMIND_TEST_REDIS_URL"])

    async def scenario():
        await harness.open()
        first, second = harness.store(), harness.store()
        same_session = harness.session()
        first_ready = asyncio.Event()
        release_first = asyncio.Event()
        second_attempted = asyncio.Event()

        async def holder():
            async with first.transaction(same_session):
                await first.append(same_session, Turn(query="first"))
                first_ready.set()
                await release_first.wait()

        async def waiter():
            await first_ready.wait()
            second_attempted.set()
            async with second.transaction(same_session):
                return await second.append(same_session, Turn(query="second"))

        holder_task = asyncio.create_task(holder())
        await first_ready.wait()
        waiter_task = asyncio.create_task(waiter())
        await second_attempted.wait()
        await asyncio.sleep(0.05)
        blocked_while_first_holds_lock = not waiter_task.done()
        release_first.set()
        await asyncio.gather(holder_task, waiter_task)
        same_session_turns = await second.get(same_session, limit=10)

        session_a, session_b = harness.session(), harness.session()
        entered_a, entered_b = asyncio.Event(), asyncio.Event()

        async def concurrent_append(
            store: RedisSessionStore,
            session_id: str,
            entered: asyncio.Event,
            other_entered: asyncio.Event,
            query: str,
        ):
            async with store.transaction(session_id):
                stored = await store.append(session_id, Turn(query=query))
                entered.set()
                await asyncio.wait_for(other_entered.wait(), timeout=1)
                return stored

        concurrent_a, concurrent_b = await asyncio.wait_for(
            asyncio.gather(
                concurrent_append(first, session_a, entered_a, entered_b, "a"),
                concurrent_append(second, session_b, entered_b, entered_a, "b"),
            ),
            timeout=2,
        )
        await harness.close()
        return (
            blocked_while_first_holds_lock,
            same_session_turns,
            concurrent_a,
            concurrent_b,
        )

    blocked, same_session_turns, concurrent_a, concurrent_b = _run(scenario())

    assert blocked is True
    assert [turn.query for turn in same_session_turns] == ["first", "second"]
    assert [concurrent_a.turn_index, concurrent_b.turn_index] == [1, 1]


def test_expired_owner_cannot_renew_release_or_write() -> None:
    harness = RedisHarness(os.environ["DOTAMIND_TEST_REDIS_URL"])
    request_id, run_id = uuid4(), uuid4()

    async def scenario():
        await harness.open()
        old, new = (
            harness.store(lock_lease_seconds=1, session_ttl_seconds=30),
            harness.store(lock_lease_seconds=1, session_ttl_seconds=30),
        )
        session_id = harness.session()
        async with old.transaction(session_id):
            original = await old.begin_request(session_id, request_id, "payload")
            assert original.owner_token is not None
            old_context = old._require_context(session_id)
            assert old_context.renewal_task is not None
            old_context.renewal_task.cancel()
            try:
                await old_context.renewal_task
            except asyncio.CancelledError:
                pass
            await asyncio.sleep(1.2)

            async with new.transaction(session_id):
                new_context = new._require_context(session_id)
                renewed = await old._eval(
                    _RENEW_LUA,
                    old._data_keys(old_context.base),
                    old_context.lock_value,
                    "1000",
                    "30",
                )
                await old._release(old_context)
                lock_after_release = await harness.client.get(
                    new._keys(session_id)["lock"]
                )
                with pytest.raises(SessionStoreError, match="lock_lost"):
                    await old.append(session_id, Turn(query="late append"))
                with pytest.raises(SessionStoreError, match="lock_lost"):
                    await old.complete_request_with_turn(
                        session_id,
                        request_id,
                        original.owner_token,
                        Turn(query="late complete"),
                        _public_response(run_id),
                        run_id,
                    )
                with pytest.raises(SessionStoreError, match="lock_lost"):
                    await old.fail_request(session_id, request_id, original.owner_token)
                takeover = await new.begin_request(session_id, request_id, "payload")
                assert takeover.owner_token is not None
                stored_record = await new._read_request_record(
                    new_context,
                    request_id,
                    new.request_key_hash(request_id),
                )
                assert stored_record is not None
                _, record = stored_record
                completed = await new.complete_request_with_turn(
                    session_id,
                    request_id,
                    takeover.owner_token,
                    Turn(query="new owner"),
                    _public_response(run_id),
                    run_id,
                )
            turns = await new.get(session_id, limit=10)
        await harness.close()
        return (
            renewed,
            lock_after_release,
            new_context,
            takeover,
            record,
            completed,
            turns,
        )

    (
        renewed,
        lock_after_release,
        new_context,
        takeover,
        record,
        completed,
        turns,
    ) = _run(scenario())

    assert renewed == [0, "lock_lost"]
    assert lock_after_release == new_context.lock_value
    assert record.owner_token == takeover.owner_token
    assert completed.turn_index == 1
    assert [turn.query for turn in turns] == ["new owner"]


def test_second_store_replays_completed_request_and_conflicts_on_payload() -> None:
    harness = RedisHarness(os.environ["DOTAMIND_TEST_REDIS_URL"])
    request_id, run_id = uuid4(), uuid4()

    async def scenario():
        await harness.open()
        first, second = harness.store(), harness.store()
        session_id = harness.session()
        async with first.transaction(session_id):
            claimed = await first.begin_request(session_id, request_id, "payload-a")
            assert claimed.owner_token is not None
            stored = await first.complete_request_with_turn(
                session_id,
                request_id,
                claimed.owner_token,
                Turn(query="one"),
                {"status": "ok", "runtime": {"run_id": str(run_id)}},
                run_id,
            )
        async with second.transaction(session_id):
            replay = await second.begin_request(session_id, request_id, "payload-a")
        async with second.transaction(session_id):
            conflict = await second.begin_request(session_id, request_id, "payload-b")
        turns = await second.get(session_id, limit=10)
        await harness.close()
        return stored, replay, conflict, turns

    stored, replay, conflict, turns = _run(scenario())

    assert stored.turn_index == 1
    assert replay.action == "replay"
    assert replay.cached_public_response == {"status": "ok", "runtime": {"run_id": str(run_id)}}
    assert conflict.action == "conflict"
    assert [turn.turn_index for turn in turns] == [1]


def test_rebuilt_store_recovers_turn_and_completed_request() -> None:
    harness = RedisHarness(os.environ["DOTAMIND_TEST_REDIS_URL"])
    request_id, run_id = uuid4(), uuid4()

    async def scenario():
        await harness.open()
        original = harness.store()
        session_id = harness.session()
        async with original.transaction(session_id):
            claim = await original.begin_request(session_id, request_id, "payload")
            assert claim.owner_token is not None
            await original.complete_request_with_turn(
                session_id,
                request_id,
                claim.owner_token,
                Turn(query="persisted"),
                {"status": "ok"},
                run_id,
            )
        rebuilt = harness.store()
        turns = await rebuilt.get(session_id, limit=10)
        async with rebuilt.transaction(session_id):
            replay = await rebuilt.begin_request(session_id, request_id, "payload")
        await harness.close()
        return turns, replay

    turns, replay = _run(scenario())

    assert [turn.query for turn in turns] == ["persisted"]
    assert replay.action == "replay"
