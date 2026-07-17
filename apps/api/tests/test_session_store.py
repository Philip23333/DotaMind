"""Tests for InMemorySessionStore.

Covers: empty get, append+get, monotonic index, limit truncation,
max_turns trim (counter not reset), session isolation, LRU eviction,
lock cleanup on eviction, snapshot copy, concurrent serialisation.
"""

import asyncio

import pytest

from app.agentic.conversation.models import Turn
from app.application.session_store import InMemorySessionStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _turn(**kwargs) -> Turn:
    return Turn(query=kwargs.pop("query", "test query"), **kwargs)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGet:
    def test_unknown_session_returns_empty(self):
        store = InMemorySessionStore()
        assert _run(store.get("nonexistent", limit=5)) == []

    def test_returns_snapshot_copy(self):
        store = InMemorySessionStore()
        _run(store.append("s1", _turn()))
        result = _run(store.get("s1", limit=5))
        result.clear()
        assert len(_run(store.get("s1", limit=5))) == 1

    def test_limit_returns_newest(self):
        store = InMemorySessionStore()
        for i in range(5):
            _run(store.append("s1", _turn(query=f"q{i}")))
        result = _run(store.get("s1", limit=3))
        assert len(result) == 3
        # Newest 3 turns: index 3, 4, 5
        assert result[0].turn_index == 3
        assert result[-1].turn_index == 5

    def test_limit_larger_than_stored(self):
        store = InMemorySessionStore()
        _run(store.append("s1", _turn()))
        result = _run(store.get("s1", limit=99))
        assert len(result) == 1

    def test_chronological_order(self):
        store = InMemorySessionStore()
        for i in range(3):
            _run(store.append("s1", _turn(query=f"q{i}")))
        result = _run(store.get("s1", limit=10))
        assert [t.turn_index for t in result] == [1, 2, 3]


class TestAppend:
    def test_assigns_monotonic_index(self):
        store = InMemorySessionStore()
        for _ in range(3):
            _run(store.append("s1", _turn()))
        turns = _run(store.get("s1", limit=10))
        assert [t.turn_index for t in turns] == [1, 2, 3]

    def test_does_not_mutate_input_turn(self):
        store = InMemorySessionStore()
        original = _turn()
        assert original.turn_index == 0  # placeholder
        stored = _run(store.append("s1", original))
        assert stored.turn_index == 1
        assert original.turn_index == 0  # unchanged

    def test_max_turns_trims_oldest_not_counter(self):
        store = InMemorySessionStore(max_turns_per_session=3)
        for _ in range(5):
            _run(store.append("s1", _turn()))
        turns = _run(store.get("s1", limit=10))
        assert len(turns) == 3
        # Counter survived the trim: next index is 6, not reset
        stored = _run(store.append("s1", _turn()))
        assert stored.turn_index == 6

    def test_session_isolation(self):
        store = InMemorySessionStore()
        _run(store.append("A", _turn(query="query-A")))
        _run(store.append("B", _turn(query="query-B")))
        assert _run(store.get("A", limit=5))[0].query == "query-A"
        assert _run(store.get("B", limit=5))[0].query == "query-B"
        # Separate indices per session
        assert _run(store.get("A", limit=5))[0].turn_index == 1
        assert _run(store.get("B", limit=5))[0].turn_index == 1


class TestLRUEviction:
    def test_oldest_session_evicted_at_capacity(self):
        store = InMemorySessionStore(max_sessions=2)
        _run(store.append("s1", _turn()))
        _run(store.append("s2", _turn()))
        _run(store.append("s3", _turn()))  # evicts s1 (LRU)
        assert _run(store.get("s1", limit=5)) == []
        assert len(_run(store.get("s2", limit=5))) == 1
        assert len(_run(store.get("s3", limit=5))) == 1

    def test_read_refreshes_lru_order(self):
        store = InMemorySessionStore(max_sessions=2)
        _run(store.append("s1", _turn()))
        _run(store.append("s2", _turn()))
        _run(store.get("s1", limit=1))  # access s1 → now s2 is LRU
        _run(store.append("s3", _turn()))  # evicts s2
        assert len(_run(store.get("s1", limit=5))) == 1  # s1 survived
        assert _run(store.get("s2", limit=5)) == []

    def test_lock_deleted_on_eviction(self):
        store = InMemorySessionStore(max_sessions=1)
        _run(store.get_lock("s1"))  # creates lock
        _run(store.append("s1", _turn()))
        _run(store.append("s2", _turn()))  # evicts s1
        assert "s1" not in store._locks


class TestLock:
    def test_same_session_same_lock(self):
        store = InMemorySessionStore()
        lock_a = _run(store.get_lock("s1"))
        lock_b = _run(store.get_lock("s1"))
        assert lock_a is lock_b

    def test_different_sessions_different_locks(self):
        store = InMemorySessionStore()
        lock_a = _run(store.get_lock("s1"))
        lock_b = _run(store.get_lock("s2"))
        assert lock_a is not lock_b

    def test_concurrent_appends_serialised_no_duplicate_index(self):
        """Three concurrent append transactions for the same session must
        produce unique, monotonically increasing turn_index values."""
        store = InMemorySessionStore()

        async def _append_with_lock(query: str) -> None:
            lock = await store.get_lock("shared")
            async with lock:
                history = await store.get("shared", limit=10)
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
