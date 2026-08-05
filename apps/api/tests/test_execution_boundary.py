import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agentic.graph import AgentGraphRunner
from app.agentic.nodes import attempt_finalize_node, response_node
from app.agentic.nodes.run_finalize import run_finalize_node
from app.agentic.nodes.run_init import run_init_node
from app.agentic.runtime.clock import SystemClock
from app.agentic.runtime.errors import AgentExecutionError, NodeExecutionFailure
from app.agentic.state import AgentRunState
from app.api.v1.routes import plan
from app.api.v1.schemas import PlanRequest
from app.application.plan_service import PlanService
from app.application.session_store import InMemorySessionStore
from app.core.config import RuntimePolicy
from app.main import metrics
from app.observability import IDEMPOTENCY, RUNS


def _completed_state(state: AgentRunState) -> AgentRunState:
    clock = SystemClock()
    state.status = "insufficient_tools"
    state.reason = "no registered tool"
    run_init_node(state, RuntimePolicy(), clock)
    attempt_finalize_node(state, clock)
    run_finalize_node(state, clock)
    return response_node(state)


class ExplodingRunner:
    async def run(self, state: AgentRunState) -> AgentRunState:
        raise AgentExecutionError("tool_execution")


class CompletingRunner:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, state: AgentRunState) -> AgentRunState:
        self.calls += 1
        return _completed_state(state)


class BlockingRunner:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run(self, state: AgentRunState) -> AgentRunState:
        self.started.set()
        await asyncio.Event().wait()
        return state


class CompletionRaceStore(InMemorySessionStore):
    def __init__(self) -> None:
        super().__init__()
        self.committed = asyncio.Event()
        self.release = asyncio.Event()

    async def complete_request_with_turn(self, *args, **kwargs):
        result = await super().complete_request_with_turn(*args, **kwargs)
        self.committed.set()
        await self.release.wait()
        return result


class ReturningGraph:
    async def ainvoke(self, state: AgentRunState):
        return _completed_state(state)


class FailingGraph:
    async def ainvoke(self, state: AgentRunState):
        raise NodeExecutionFailure(state, "response", "execution")


class CancelledGraph:
    async def ainvoke(self, state: AgentRunState):
        raise asyncio.CancelledError


def _graph_runner(graph) -> AgentGraphRunner:
    runner = object.__new__(AgentGraphRunner)
    runner.clock = SystemClock()
    runner.graph = graph
    return runner


def _service(store: InMemorySessionStore, runner) -> PlanService:
    service = PlanService(session_store=store)
    service.runner = runner  # type: ignore[assignment]
    return service


def test_unhandled_error_is_not_completed_and_request_id_can_retry_once() -> None:
    store = InMemorySessionStore()
    service = _service(store, ExplodingRunner())
    session_id, request_id = uuid4(), uuid4()

    async def scenario():
        with pytest.raises(AgentExecutionError):
            await service.run("query", session_id=session_id, request_id=request_id)
        record = store._sessions[str(session_id)].request_records[str(request_id)]
        service.runner = CompletingRunner()  # type: ignore[assignment]
        result = await service.run("query", session_id=session_id, request_id=request_id)
        return record, result, await store.get(str(session_id), limit=5)

    record, result, turns = asyncio.run(scenario())

    assert record.status == "failed"
    assert result.idempotency_status == "executed"
    assert len(turns) == 1


def test_cancellation_after_atomic_completion_keeps_one_completed_turn() -> None:
    store = CompletionRaceStore()
    service = _service(store, CompletingRunner())
    session_id, request_id = uuid4(), uuid4()

    async def scenario():
        task = asyncio.create_task(
            service.run("query", session_id=session_id, request_id=request_id)
        )
        await store.committed.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        replay = await service.run("query", session_id=session_id, request_id=request_id)
        return replay, await store.get(str(session_id), limit=5)

    executed = IDEMPOTENCY.labels("memory", "executed")._value
    cancelled = IDEMPOTENCY.labels("memory", "cancelled")._value
    before = executed.get(), cancelled.get()
    replay, turns = asyncio.run(scenario())

    assert replay.idempotency_status == "replayed"
    assert len(turns) == 1
    assert executed.get() - before[0] == 1
    assert cancelled.get() - before[1] == 0


def test_cancellation_before_commit_fails_request_without_turn() -> None:
    store = InMemorySessionStore()
    runner = BlockingRunner()
    service = _service(store, runner)
    session_id, request_id = uuid4(), uuid4()
    cancelled = IDEMPOTENCY.labels("memory", "cancelled")._value

    async def scenario():
        task = asyncio.create_task(
            service.run("query", session_id=session_id, request_id=request_id)
        )
        await runner.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        record = store._sessions[str(session_id)].request_records[str(request_id)]
        return record, await store.get(str(session_id), limit=5)

    before = cancelled.get()
    record, turns = asyncio.run(scenario())

    assert record.status == "failed"
    assert turns == []
    assert cancelled.get() - before == 1


def test_route_maps_unhandled_agent_error_to_safe_500() -> None:
    store = InMemorySessionStore()
    service = _service(store, ExplodingRunner())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(plan_service=service)))

    async def scenario():
        return await plan(
            PlanRequest(query="query"), request
        )

    response = asyncio.run(scenario())

    assert response.status_code == 500
    assert b'"error_code":"execution_error"' in response.body
    assert b'"reason":"execution failed"' in response.body


def test_route_maps_plain_exception_to_the_same_safe_500() -> None:
    class RuntimeExplodingService:
        async def run(self, *args):
            raise RuntimeError("sentinel-internal-detail")

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(plan_service=RuntimeExplodingService()))
    )

    response = asyncio.run(
        plan(PlanRequest(query="query"), request)
    )

    assert response.status_code == 500
    assert response.body == (
        b'{"status":"error","reason":"execution failed",'
        b'"response_type":"execution_error","error_code":"execution_error"}'
    )
    assert b"sentinel" not in response.body


def test_route_maps_public_response_validation_failure_to_safe_500() -> None:
    class MalformedService:
        async def run(self, *args):
            return SimpleNamespace(public_response={"status": "ok"})

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(plan_service=MalformedService()))
    )

    response = asyncio.run(
        plan(PlanRequest(query="query"), request)
    )

    assert response.status_code == 500
    assert b'"error_code":"execution_error"' in response.body


def test_route_does_not_convert_cancellation_to_http_500() -> None:
    class CancelledService:
        async def run(self, *args):
            raise asyncio.CancelledError

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(plan_service=CancelledService()))
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            plan(PlanRequest(query="query"), request)
        )


def test_runner_records_one_run_only_after_response_success() -> None:
    metric = RUNS.labels("insufficient_tools", "capability_boundary")._value
    before = metric.get()

    result = asyncio.run(
        _graph_runner(ReturningGraph()).run(AgentRunState(query="query", game="dota2"))
    )

    assert result.response is not None
    assert metric.get() - before == 1


def test_response_failure_records_failed_run_without_completed_run() -> None:
    failed = RUNS.labels("error", "execution_error")._value
    completed = RUNS.labels("insufficient_tools", "capability_boundary")._value
    before = failed.get(), completed.get()

    with pytest.raises(AgentExecutionError):
        asyncio.run(
            _graph_runner(FailingGraph()).run(AgentRunState(query="query", game="dota2"))
        )

    assert failed.get() - before[0] == 1
    assert completed.get() - before[1] == 0


def test_runner_cancellation_records_cancelled_once_and_propagates() -> None:
    cancelled = RUNS.labels("cancelled", "request_cancelled")._value
    failed = RUNS.labels("error", "execution_error")._value
    before = cancelled.get(), failed.get()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            _graph_runner(CancelledGraph()).run(AgentRunState(query="query", game="dota2"))
        )

    assert cancelled.get() - before[0] == 1
    assert failed.get() - before[1] == 0


def test_metrics_endpoint_exposes_runtime_collectors_without_request_data() -> None:
    response = metrics()

    assert response.status_code == 200
    assert b"dotamind_agent_runs_total" in response.body
    assert b"dotamind_controller_calls_total" in response.body
    assert b"dotamind_critic_reviews_total" in response.body
    assert b"dotamind_tool_calls_total" in response.body
    assert b"dotamind_tool_call_duration_seconds" in response.body
    assert b"dotamind_agent_tool_calls_total" not in response.body
    assert b"query" not in response.body
