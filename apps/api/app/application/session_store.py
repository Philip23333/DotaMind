"""Session store: persistence layer for multi-turn conversation history.

Phase 1 ships InMemorySessionStore (LRU, per-session async lock, single
process only).  The abstract base defines an async interface so Phase 2 can
drop in a Redis backend without changing callers.

Phase 1 limitation: InMemorySessionStore provides correctness only within a
single process / single Uvicorn worker.  Multi-worker or multi-process
deployments require a distributed store (Phase 2, Redis).
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field

from app.agentic.conversation.models import Turn


# ---------------------------------------------------------------------------
# Internal session container
# ---------------------------------------------------------------------------


@dataclass
class _SessionData:
    """Per-session state managed by InMemorySessionStore."""

    turns: list[Turn] = field(default_factory=list)
    # Monotonically increasing counter; never reset even after turn eviction.
    next_turn_index: int = 1


# ---------------------------------------------------------------------------
# Abstract interface (async so Phase 2 Redis backend is a drop-in)
# ---------------------------------------------------------------------------


class SessionStore(ABC):
    """Abstract session store.  All methods are async."""

    @abstractmethod
    async def get(self, session_id: str, limit: int) -> list[Turn]:
        """Return up to *limit* most-recent turns in chronological order.

        Returns an empty list when the session is unknown.
        The returned list is a snapshot copy; callers must not mutate it.
        """

    @abstractmethod
    async def append(self, session_id: str, turn: Turn) -> Turn:
        """Append *turn* to the session, assign its monotonic turn_index.

        Returns the stored Turn with turn_index set by the store.
        Callers must NOT use the turn_index on the input object.
        """

    @abstractmethod
    async def get_lock(self, session_id: str) -> asyncio.Lock:
        """Return the per-session async lock.

        The lock must be held for the full get → run → append transaction to
        preserve single-session ordering.  The lock object is stable for the
        lifetime of the session.
        """


# ---------------------------------------------------------------------------
# Phase 1: in-process LRU store
# ---------------------------------------------------------------------------


class InMemorySessionStore(SessionStore):
    """LRU in-memory session store with per-session async locking.

    Eviction: when ``max_sessions`` is reached the least-recently-used session
    (and its lock) is evicted.  Any read or write refreshes the LRU order.

    Turn capacity: each session keeps at most ``max_turns_per_session`` turns.
    Older turns are dropped from the front of the list; the monotonic counter
    is never reset so turn_index stays unique for the lifetime of the session.

    Concurrency: the per-session Lock covers the full
    get → runner.run → append cycle in PlanService, guaranteeing that
    concurrent requests for the same session are serialised.  This guarantee
    holds only within a single process; multi-worker deployments need a
    distributed lock (Phase 2).
    """

    def __init__(
        self,
        max_sessions: int = 1000,
        max_turns_per_session: int = 50,
    ) -> None:
        self._max_sessions = max_sessions
        self._max_turns = max_turns_per_session
        # OrderedDict gives O(1) LRU move_to_end / popitem.
        self._sessions: OrderedDict[str, _SessionData] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # SessionStore interface
    # ------------------------------------------------------------------

    async def get(self, session_id: str, limit: int) -> list[Turn]:
        if session_id not in self._sessions:
            return []
        self._sessions.move_to_end(session_id)  # refresh LRU on read
        data = self._sessions[session_id]
        return list(data.turns[-limit:])  # snapshot copy, chronological

    async def append(self, session_id: str, turn: Turn) -> Turn:
        if session_id not in self._sessions:
            self._evict_if_full()
            self._sessions[session_id] = _SessionData()
        self._sessions.move_to_end(session_id)  # refresh LRU on write
        data = self._sessions[session_id]

        # Assign monotonic index atomically (we hold the session lock).
        stored = turn.model_copy(update={"turn_index": data.next_turn_index})
        data.next_turn_index += 1
        data.turns.append(stored)

        # Trim oldest turns while preserving the counter.
        if len(data.turns) > self._max_turns:
            data.turns = data.turns[-self._max_turns :]

        return stored

    async def get_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_if_full(self) -> None:
        """Evict least-recently-used session(s) until under capacity."""
        while len(self._sessions) >= self._max_sessions:
            evicted_id, _ = self._sessions.popitem(last=False)
            self._locks.pop(evicted_id, None)
