import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.agentic.conversation.models import Turn
from app.agentic.nodes import attempt_finalize_node, response_node
from app.agentic.nodes.run_finalize import run_finalize_node
from app.agentic.nodes.run_init import run_init_node
from app.agentic.runtime.clock import SystemClock
from app.agentic.state import AgentRunState
from app.application.idempotency import IdempotencyConflictError, build_request_hash
from app.application.plan_service import PlanService
from app.application.session_store import InMemorySessionStore
from app.core.config import RuntimePolicy


def _complete_state(state: AgentRunState) -> AgentRunState:
    """Return a deterministic, finalized no-tool response without an LLM."""

    clock = SystemClock()
    state.status = "insufficient_tools"
    state.reason = "no registered tool"
    state.response_type = "capability_boundary"
    run_init_node(state, RuntimePolicy(), clock)
    state.add_trace("controller", "no registered tool", "completed")
    attempt_finalize_node(state, clock)
    run_finalize_node(state, clock)
    return response_node(state)


class CountingRunner:
    def __init__(self, *, block: asyncio.Event | None = None) -> None:
        self.calls = 0
        self.received_request_ids: list[UUID | None] = []
        self.started = asyncio.Event()
        self.block = block

    async def run(self, state: AgentRunState) -> AgentRunState:
        self.calls += 1
        self.received_request_ids.append(state.internal_request_id)
        self.started.set()
        if self.block is not None:
            await self.block.wait()
        return _complete_state(state)


def _service(store: InMemorySessionStore, runner: CountingRunner) -> PlanService:
    service = PlanService(session_store=store)
    service.runner = runner  # type: ignore[assignment]
    return service


def test_request_hash_uses_exact_validated_inputs_and_canonical_json() -> None:
    assert build_request_hash(query="Lina", game="dota2") == build_request_hash(
        game="dota2", query="Lina"
    )
    assert build_request_hash(query="Lina", game="dota2") != build_request_hash(
        query="lina", game="dota2"
    )


def test_completed_request_replays_public_response_once_and_preserves_run_id() -> None:
    store = InMemorySessionStore()
    runner = CountingRunner()
    service = _service(store, runner)
    session_id, request_id = uuid4(), uuid4()

    async def _scenario():
        first = await service.run("same request", session_id=session_id, request_id=request_id)
        second = await service.run("same request", session_id=session_id, request_id=request_id)
        turns = await store.get(str(session_id), limit=5)
        return first, second, turns

    first, second, turns = asyncio.run(_scenario())

    assert runner.calls == 1
    assert runner.received_request_ids == [request_id]
    assert first.idempotency_status == "executed"
    assert first.state is not None
    assert first.state.run_context is not None
    assert first.state.run_context.request_id == request_id
    assert second.idempotency_status == "replayed"
    assert second.state is None
    assert second.public_response == first.public_response
    assert second.public_response["runtime"]["run_id"] == str(first.state.run_context.run_id)
    assert [turn.turn_index for turn in turns] == [1]


def test_concurrent_same_request_waits_and_executes_one_graph() -> None:
    release = asyncio.Event()
    store = InMemorySessionStore()
    runner = CountingRunner(block=release)
    service = _service(store, runner)
    session_id, request_id = uuid4(), uuid4()

    async def _scenario():
        first_task = asyncio.create_task(
            service.run("same request", session_id=session_id, request_id=request_id)
        )
        await runner.started.wait()
        second_task = asyncio.create_task(
            service.run("same request", session_id=session_id, request_id=request_id)
        )
        await asyncio.sleep(0)
        assert runner.calls == 1
        release.set()
        first, second = await asyncio.gather(first_task, second_task)
        turns = await store.get(str(session_id), limit=5)
        return first, second, turns

    first, second, turns = asyncio.run(_scenario())

    assert runner.calls == 1
    assert {first.idempotency_status, second.idempotency_status} == {"executed", "replayed"}
    assert first.public_response == second.public_response
    assert len(turns) == 1


def test_same_request_key_with_different_inputs_conflicts_without_second_turn() -> None:
    store = InMemorySessionStore()
    runner = CountingRunner()
    service = _service(store, runner)
    session_id, request_id = uuid4(), uuid4()

    async def _scenario():
        await service.run("first request", session_id=session_id, request_id=request_id)
        with pytest.raises(IdempotencyConflictError):
            await service.run("different request", session_id=session_id, request_id=request_id)
        return await store.get(str(session_id), limit=5)

    turns = asyncio.run(_scenario())

    assert runner.calls == 1
    assert len(turns) == 1
    assert turns[0].query == "first request"


def test_cancelled_owner_marks_failed_and_later_request_takes_over() -> None:
    release = asyncio.Event()
    store = InMemorySessionStore()
    runner = CountingRunner(block=release)
    service = _service(store, runner)
    session_id, request_id = uuid4(), uuid4()

    async def _scenario():
        owner = asyncio.create_task(
            service.run("same request", session_id=session_id, request_id=request_id)
        )
        await runner.started.wait()
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        runner.block = None
        takeover = await service.run(
            "same request", session_id=session_id, request_id=request_id
        )
        turns = await store.get(str(session_id), limit=5)
        return takeover, turns

    takeover, turns = asyncio.run(_scenario())

    assert runner.calls == 2
    assert takeover.idempotency_status == "executed"
    assert len(turns) == 1


def test_expired_completed_record_executes_a_new_request() -> None:
    now = datetime(2026, 7, 23, tzinfo=UTC)

    def _now() -> datetime:
        return now

    store = InMemorySessionStore(request_record_ttl_seconds=60, now=_now)
    runner = CountingRunner()
    service = _service(store, runner)
    session_id, request_id = uuid4(), uuid4()

    async def _scenario():
        nonlocal now
        first = await service.run("same request", session_id=session_id, request_id=request_id)
        now += timedelta(seconds=61)
        second = await service.run("same request", session_id=session_id, request_id=request_id)
        turns = await store.get(str(session_id), limit=5)
        return first, second, turns

    first, second, turns = asyncio.run(_scenario())

    assert runner.calls == 2
    assert first.idempotency_status == "executed"
    assert second.idempotency_status == "executed"
    assert [turn.turn_index for turn in turns] == [1, 2]


def test_request_record_cache_is_public_only_and_is_returned_as_a_copy() -> None:
    sentinel = "HISTORY_MUST_NOT_BE_CACHED"
    store = InMemorySessionStore()
    runner = CountingRunner()
    service = _service(store, runner)
    session_id, request_id = uuid4(), uuid4()

    async def _scenario():
        async with store.transaction(str(session_id)):
            await store.append(
                str(session_id), Turn(query="earlier", response_summary=sentinel)
            )
        first = await service.run("same request", session_id=session_id, request_id=request_id)
        first.public_response["reason"] = "mutated by caller"
        second = await service.run("same request", session_id=session_id, request_id=request_id)
        record = store._sessions[str(session_id)].request_records[str(request_id)]
        return second, record

    replayed, record = asyncio.run(_scenario())

    assert sentinel not in str(record.cached_public_response)
    assert replayed.public_response["reason"] == "no registered tool"


def test_request_record_capacity_preserves_in_progress_records() -> None:
    store = InMemorySessionStore(max_request_records_per_session=1)
    session_id = "session"
    first_id, second_id = uuid4(), uuid4()

    async def _scenario():
        async with store.transaction(session_id):
            first = await store.begin_request(session_id, first_id, "hash-one")
            second = await store.begin_request(session_id, second_id, "hash-two")
            assert first.owner_token is not None and second.owner_token is not None
            assert len(store._sessions[session_id].request_records) == 2
            await store.fail_request(session_id, first_id, first.owner_token)
            return store._sessions[session_id].request_records

    records = asyncio.run(_scenario())

    assert list(records) == [str(second_id)]


def test_atomic_completion_rejects_a_non_owner_without_writing_a_turn() -> None:
    store = InMemorySessionStore()
    session_id, request_id = "session", uuid4()

    async def _scenario():
        async with store.transaction(session_id):
            begin = await store.begin_request(session_id, request_id, "request-hash")
            assert begin.owner_token is not None
            with pytest.raises(RuntimeError, match="current request owner"):
                await store.complete_request_with_turn(
                    session_id,
                    request_id,
                    uuid4(),
                    Turn(query="query"),
                    {"status": "ok"},
                    uuid4(),
                )
            await store.fail_request(session_id, request_id, begin.owner_token)
        return await store.get(session_id, limit=5)

    assert asyncio.run(_scenario()) == []
