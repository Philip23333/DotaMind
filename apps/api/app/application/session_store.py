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
from contextlib import AbstractAsyncContextManager, asynccontextmanager
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

        This method is part of the same atomic operation as ``get`` and must
        be called by the task currently inside ``transaction(session_id)``.
        Implementations must reject writes outside that transaction rather
        than creating an unlocked session that LRU eviction could remove.
        """

    @abstractmethod
    def transaction(self, session_id: str) -> AbstractAsyncContextManager[None]:
        """Serialize one complete get → run → append transaction."""


# ---------------------------------------------------------------------------
# Phase 1: in-process LRU store
# ---------------------------------------------------------------------------


class InMemorySessionStore(SessionStore):
    """LRU in-memory session store with per-session async locking.

    Eviction: inactive least-recently-used sessions are evicted above
    ``max_sessions``. Active and waiting transactions hold leases and are never
    evicted; capacity may therefore be temporarily exceeded under concurrency.

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
        # Includes both current lock holders and waiters. This prevents the
        # lock-release/reacquire window from permitting an unsafe eviction.
        self._leases: dict[str, int] = {}
        # The task which currently owns each session lock.  A lease alone is
        # insufficient here: it can belong to a waiter which must not append.
        self._holders: dict[str, asyncio.Task[object]] = {}

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
        holder = self._holders.get(session_id)
        if holder is None or holder is not asyncio.current_task():
            raise RuntimeError(
                "SessionStore.append() must be called inside "
                "transaction(session_id) by the current task"
            )
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionData()
            self._sessions.move_to_end(session_id)
            self._evict_to_capacity()
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

    @asynccontextmanager
    async def transaction(self, session_id: str):
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        self._leases[session_id] = self._leases.get(session_id, 0) + 1
        acquired = False
        try:
            await lock.acquire()
            acquired = True
            current_task = asyncio.current_task()
            if current_task is None:  # pragma: no cover - asyncio guarantees a task.
                raise RuntimeError("SessionStore.transaction() requires an asyncio task")
            self._holders[session_id] = current_task
            yield
        finally:
            if acquired:
                self._holders.pop(session_id, None)
                lock.release()
            remaining = self._leases[session_id] - 1
            if remaining == 0:
                self._leases.pop(session_id)
                if session_id not in self._sessions:
                    self._locks.pop(session_id, None)
            else:
                self._leases[session_id] = remaining
            self._evict_to_capacity()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_to_capacity(self) -> None:
        """Evict inactive LRU sessions until at or below capacity."""
        while len(self._sessions) > self._max_sessions:
            evicted_id = next(
                (
                    candidate
                    for candidate in self._sessions
                    if self._leases.get(candidate, 0) == 0
                ),
                None,
            )
            if evicted_id is None:
                return
            self._sessions.pop(evicted_id)
            self._locks.pop(evicted_id, None)
