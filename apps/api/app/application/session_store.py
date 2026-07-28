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
import copy
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.agentic.conversation.models import Turn
from app.application.idempotency import RequestBeginResult, RequestRecord

# ---------------------------------------------------------------------------
# Internal session container
# ---------------------------------------------------------------------------


@dataclass
class _SessionData:
    """Per-session state managed by InMemorySessionStore."""

    turns: list[Turn] = field(default_factory=list)
    # Monotonically increasing counter; never reset even after turn eviction.
    next_turn_index: int = 1
    request_records: OrderedDict[str, RequestRecord] = field(default_factory=OrderedDict)


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
    async def begin_request(
        self,
        session_id: str,
        request_id: UUID,
        request_hash: str,
    ) -> RequestBeginResult:
        """Claim, replay, or reject an idempotent request inside its transaction."""

    @abstractmethod
    async def complete_request_with_turn(
        self,
        session_id: str,
        request_id: UUID,
        owner_token: UUID,
        turn: Turn,
        public_response: dict[str, Any],
        run_id: UUID,
    ) -> Turn:
        """Atomically append a Turn and mark the owned request completed."""

    @abstractmethod
    async def fail_request(
        self,
        session_id: str,
        request_id: UUID,
        owner_token: UUID,
    ) -> None:
        """Mark an owned in-progress request failed without appending a Turn."""

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
        request_record_ttl_seconds: int = 3600,
        max_request_records_per_session: int = 200,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._max_sessions = max_sessions
        self._max_turns = max_turns_per_session
        self._request_record_ttl = timedelta(seconds=request_record_ttl_seconds)
        self._max_request_records = max_request_records_per_session
        self._now = now or (lambda: datetime.now(UTC))
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
        self._require_holder(session_id, "append")
        return self._append_locked(session_id, turn)

    async def begin_request(
        self,
        session_id: str,
        request_id: UUID,
        request_hash: str,
    ) -> RequestBeginResult:
        self._require_holder(session_id, "begin_request")
        data = self._get_or_create_session(session_id)
        self._purge_expired_request_records(data)
        key = str(request_id)
        existing = data.request_records.get(key)
        if existing is not None:
            data.request_records.move_to_end(key)
            if existing.request_hash != request_hash:
                return RequestBeginResult(
                    action="conflict",
                    existing_request_hash=existing.request_hash,
                )
            if existing.status == "completed":
                if existing.cached_public_response is None:
                    raise RuntimeError("completed request record missing public response")
                return RequestBeginResult(
                    action="replay",
                    cached_public_response=copy.deepcopy(existing.cached_public_response),
                )

        now = self._now()
        owner_token = uuid4()
        data.request_records[key] = RequestRecord(
            request_id=request_id,
            request_hash=request_hash,
            status="in_progress",
            owner_token=owner_token,
            started_at=now,
            expires_at=now + self._request_record_ttl,
        )
        data.request_records.move_to_end(key)
        self._trim_request_records(data)
        return RequestBeginResult(action="execute", owner_token=owner_token)

    async def complete_request_with_turn(
        self,
        session_id: str,
        request_id: UUID,
        owner_token: UUID,
        turn: Turn,
        public_response: dict[str, Any],
        run_id: UUID,
    ) -> Turn:
        self._require_holder(session_id, "complete_request_with_turn")
        data = self._get_or_create_session(session_id)
        key = str(request_id)
        record = data.request_records.get(key)
        if record is None or record.status != "in_progress" or record.owner_token != owner_token:
            raise RuntimeError("request completion requires the current request owner")
        stored = self._append_locked(session_id, turn)
        now = self._now()
        data.request_records[key] = record.model_copy(
            update={
                "status": "completed",
                "run_id": run_id,
                "cached_public_response": copy.deepcopy(public_response),
                "turn_index": stored.turn_index,
                "completed_at": now,
            }
        )
        data.request_records.move_to_end(key)
        self._trim_request_records(data)
        return stored

    async def fail_request(
        self,
        session_id: str,
        request_id: UUID,
        owner_token: UUID,
    ) -> None:
        self._require_holder(session_id, "fail_request")
        data = self._sessions.get(session_id)
        if data is None:
            return
        key = str(request_id)
        record = data.request_records.get(key)
        if record is None or record.status != "in_progress" or record.owner_token != owner_token:
            return
        data.request_records[key] = record.model_copy(
            update={"status": "failed", "completed_at": self._now()}
        )
        data.request_records.move_to_end(key)
        self._trim_request_records(data)

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

    def _require_holder(self, session_id: str, operation: str) -> None:
        holder = self._holders.get(session_id)
        if holder is None or holder is not asyncio.current_task():
            raise RuntimeError(
                f"SessionStore.{operation}() must be called inside "
                "transaction(session_id) by the current task"
            )

    def _get_or_create_session(self, session_id: str) -> _SessionData:
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionData()
            self._sessions.move_to_end(session_id)
            self._evict_to_capacity()
        self._sessions.move_to_end(session_id)
        return self._sessions[session_id]

    def _append_locked(self, session_id: str, turn: Turn) -> Turn:
        data = self._get_or_create_session(session_id)
        stored = turn.model_copy(update={"turn_index": data.next_turn_index})
        data.next_turn_index += 1
        data.turns.append(stored)
        if len(data.turns) > self._max_turns:
            data.turns = data.turns[-self._max_turns :]
        return stored

    def _purge_expired_request_records(self, data: _SessionData) -> None:
        now = self._now()
        expired = [
            key
            for key, record in data.request_records.items()
            if record.status != "in_progress" and record.expires_at <= now
        ]
        for key in expired:
            data.request_records.pop(key)

    def _trim_request_records(self, data: _SessionData) -> None:
        while len(data.request_records) > self._max_request_records:
            evicted_key = next(
                (
                    key
                    for key, record in data.request_records.items()
                    if record.status != "in_progress"
                ),
                None,
            )
            if evicted_key is None:
                return
            data.request_records.pop(evicted_key)

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
