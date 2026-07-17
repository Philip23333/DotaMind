"""Tests for InMemorySessionStore.

Covers: empty get, append+get, monotonic index, limit truncation,
max_turns trim (counter not reset), session isolation, LRU eviction,
lock cleanup on eviction, snapshot copy, concurrent serialisation.
"""

import asyncio

from app.agentic.conversation.models import Turn
from app.application.session_store import InMemorySessionStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _turn(**kwargs) -> Turn:
    return Turn(query=kwargs.pop("query", "test query"), **kwargs)


def _run(coro):
    return asyncio.run(coro)


def _append(store: InMemorySessionStore, session_id: str, turn: Turn) -> Turn:
    async def _write() -> Turn:
        async with store.transaction(session_id):
            return await store.append(session_id, turn)

    return _run(_write())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGet:
    def test_unknown_session_returns_empty(self):
        store = InMemorySessionStore()
        assert _run(store.get("nonexistent", limit=5)) == []

    def test_returns_snapshot_copy(self):
        store = InMemorySessionStore()
        _append(store, "s1", _turn())
        result = _run(store.get("s1", limit=5))
        result.clear()
        assert len(_run(store.get("s1", limit=5))) == 1

    def test_limit_returns_newest(self):
        store = InMemorySessionStore()
        for i in range(5):
            _append(store, "s1", _turn(query=f"q{i}"))
        result = _run(store.get("s1", limit=3))
        assert len(result) == 3
        # Newest 3 turns: index 3, 4, 5
        assert result[0].turn_index == 3
        assert result[-1].turn_index == 5

    def test_limit_larger_than_stored(self):
        store = InMemorySessionStore()
        _append(store, "s1", _turn())
        result = _run(store.get("s1", limit=99))
        assert len(result) == 1

    def test_chronological_order(self):
        store = InMemorySessionStore()
        for i in range(3):
            _append(store, "s1", _turn(query=f"q{i}"))
        result = _run(store.get("s1", limit=10))
        assert [t.turn_index for t in result] == [1, 2, 3]


class TestAppend:
    def test_rejects_write_outside_current_session_transaction(self):
        store = InMemorySessionStore()

        async def _scenario() -> None:
            try:
                await store.append("s1", _turn())
            except RuntimeError as exc:
                assert "transaction(session_id)" in str(exc)
            else:  # pragma: no cover - assertion failure path
                raise AssertionError("append outside a transaction was accepted")

        _run(_scenario())

    def test_assigns_monotonic_index(self):
        store = InMemorySessionStore()
        for _ in range(3):
            _append(store, "s1", _turn())
        turns = _run(store.get("s1", limit=10))
        assert [t.turn_index for t in turns] == [1, 2, 3]

    def test_does_not_mutate_input_turn(self):
        store = InMemorySessionStore()
        original = _turn()
        assert original.turn_index == 0  # placeholder
        stored = _append(store, "s1", original)
        assert stored.turn_index == 1
        assert original.turn_index == 0  # unchanged

    def test_max_turns_trims_oldest_not_counter(self):
        store = InMemorySessionStore(max_turns_per_session=3)
        for _ in range(5):
            _append(store, "s1", _turn())
        turns = _run(store.get("s1", limit=10))
        assert len(turns) == 3
        # Counter survived the trim: next index is 6, not reset
        stored = _append(store, "s1", _turn())
        assert stored.turn_index == 6

    def test_session_isolation(self):
        store = InMemorySessionStore()
        _append(store, "A", _turn(query="query-A"))
        _append(store, "B", _turn(query="query-B"))
        assert _run(store.get("A", limit=5))[0].query == "query-A"
        assert _run(store.get("B", limit=5))[0].query == "query-B"
        # Separate indices per session
        assert _run(store.get("A", limit=5))[0].turn_index == 1
        assert _run(store.get("B", limit=5))[0].turn_index == 1


class TestLRUEviction:
    def test_oldest_session_evicted_at_capacity(self):
        store = InMemorySessionStore(max_sessions=2)
        _append(store, "s1", _turn())
        _append(store, "s2", _turn())
        _append(store, "s3", _turn())  # evicts s1 (LRU)
        assert _run(store.get("s1", limit=5)) == []
        assert len(_run(store.get("s2", limit=5))) == 1
        assert len(_run(store.get("s3", limit=5))) == 1

    def test_read_refreshes_lru_order(self):
        store = InMemorySessionStore(max_sessions=2)
        _append(store, "s1", _turn())
        _append(store, "s2", _turn())
        _run(store.get("s1", limit=1))  # access s1 → now s2 is LRU
        _append(store, "s3", _turn())  # evicts s2
        assert len(_run(store.get("s1", limit=5))) == 1  # s1 survived
        assert _run(store.get("s2", limit=5)) == []

    def test_lock_deleted_on_eviction(self):
        store = InMemorySessionStore(max_sessions=1)
        _append(store, "s1", _turn())
        _append(store, "s2", _turn())  # evicts s1
        assert "s1" not in store._locks


class TestTransaction:
    def test_direct_append_cannot_evict_itself_when_active_session_fills_capacity(self):
        """A caller cannot create an unlocked B while active A owns capacity."""
        store = InMemorySessionStore(max_sessions=1)

        async def _scenario() -> None:
            async with store.transaction("A"):
                await store.append("A", _turn(query="A"))
                try:
                    await store.append("B", _turn(query="B"))
                except RuntimeError as exc:
                    assert "transaction(session_id)" in str(exc)
                else:  # pragma: no cover - assertion failure path
                    raise AssertionError("cross-session append was accepted")
                assert [turn.query for turn in await store.get("A", 5)] == ["A"]
                assert await store.get("B", 5) == []

        _run(_scenario())

    def test_concurrent_appends_serialised_no_duplicate_index(self):
        """Three concurrent append transactions for the same session must
        produce unique, monotonically increasing turn_index values."""
        store = InMemorySessionStore()

        async def _append_with_lock(query: str) -> None:
            async with store.transaction("shared"):
                # Read step simulates the full get→run→append transaction.
                await store.get("shared", limit=10)
                await store.append("shared", _turn(query=query))

        async def _run_concurrent() -> None:
            await asyncio.gather(
                _append_with_lock("q1"),
                _append_with_lock("q2"),
                _append_with_lock("q3"),
            )

        asyncio.run(_run_concurrent())
        turns = asyncio.run(store.get("shared", limit=10))
        assert len(turns) == 3
        indices = [t.turn_index for t in turns]
        assert len(set(indices)) == 3, "duplicate turn_index detected"
        assert indices == sorted(indices), "turn_index not monotonic"

    def test_cancelled_waiter_does_not_release_holder_lock(self):
        store = InMemorySessionStore()

        async def _scenario():
            entered = asyncio.Event()
            release = asyncio.Event()

            async def holder():
                async with store.transaction("shared"):
                    entered.set()
                    await release.wait()
                    await store.append("shared", _turn(query="holder"))

            async def waiter():
                async with store.transaction("shared"):
                    await store.append("shared", _turn(query="waiter"))

            holder_task = asyncio.create_task(holder())
            await entered.wait()
            waiter_task = asyncio.create_task(waiter())
            await asyncio.sleep(0)
            assert store._leases["shared"] == 2
            waiter_task.cancel()
            try:
                await waiter_task
            except asyncio.CancelledError:
                pass
            assert store._locks["shared"].locked()
            assert store._leases["shared"] == 1
            release.set()
            await holder_task
            assert store._leases == {}

        asyncio.run(_scenario())

    def test_lru_never_evicts_active_session(self):
        store = InMemorySessionStore(max_sessions=1)

        async def _scenario():
            async with store.transaction("A"):
                await store.append("A", _turn(query="A"))
                original_lock = store._locks["A"]
                async with store.transaction("B"):
                    await store.append("B", _turn(query="B"))
                    assert store._leases["A"] == 1
                    assert store._locks["A"] is original_lock
                    assert (await store.get("A", 10))[0].query == "A"
                    assert len(store._sessions) == 2
                # B is the only inactive candidate, so A remains intact.
                assert store._locks["A"] is original_lock
                assert (await store.get("A", 10))[0].query == "A"

        asyncio.run(_scenario())
