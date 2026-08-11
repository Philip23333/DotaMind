from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.agentic.conversation.models import Turn
from app.agentic.runtime.streaming import PlanStreamEvent
from app.agentic.state import AgentRunState
from app.application.chat_run_executor import (
    ChatRunExecutionRequest,
    ChatRunExecutor,
)
from app.application.chat_run_repository import ChatRunRepositoryError, ChatRunSummary
from app.application.plan_service import TurnBuildResult
from app.application.run_event_bus import StoredRunEvent
from app.application.session_store import SessionStoreError


def test_chat_run_executor_uses_preallocated_id_and_commits_before_terminal_events() -> None:
    async def scenario() -> None:
        run_id = uuid4()
        session_id = uuid4()
        request_id = uuid4()
        events: list[StoredRunEvent] = []
        calls: list[str] = []
        run_repository = FakeRunRepository(calls=calls, run_id=run_id, session_id=session_id)
        runner = FakeRunner(calls=calls)
        executor = ChatRunExecutor(
            runner=runner,
            run_repository=run_repository,
            chat_repository=FakeChatRepository(calls=calls),
            session_store=FakeSessionStore(),
            memory_service=FakeMemoryService(calls=calls),
            event_bus=FakeEventBus(events, calls),
            worker_id="worker-a",
            build_turn=lambda state: _build_turn(state),
            build_response=lambda state, sid: {
                "answer": state.response["answer"],
                "session_id": str(sid),
            },
        )

        result = await executor.execute(
            ChatRunExecutionRequest(
                run_id=run_id,
                browser_id="browser-a",
                session_id=session_id,
                request_id=request_id,
                query="how many?",
                game="dota2",
            )
        )

        assert runner.state_ids == [run_id]
        assert result.run.status == "completed"
        assert calls.index("complete") < calls.index("event:result")
        assert [event.event.type for event in events] == ["status", "result", "status"]
        assert events[-1].event.status == "completed"

    asyncio.run(scenario())


def test_chat_run_executor_marks_failed_graph_without_writing_a_turn() -> None:
    async def scenario() -> None:
        run_id = uuid4()
        session_id = uuid4()
        calls: list[str] = []
        run_repository = FakeRunRepository(calls=calls, run_id=run_id, session_id=session_id)
        executor = ChatRunExecutor(
            runner=FakeRunner(calls=calls, failure=RuntimeError("boom")),
            run_repository=run_repository,
            chat_repository=FakeChatRepository(calls=calls),
            session_store=FakeSessionStore(),
            memory_service=FakeMemoryService(calls=[]),
            event_bus=FakeEventBus([], calls),
            worker_id="worker-a",
            build_turn=lambda state: _build_turn(state),
            build_response=lambda state, sid: {},
        )

        try:
            await executor.execute(
                ChatRunExecutionRequest(
                    run_id=run_id,
                    browser_id="browser-a",
                    session_id=session_id,
                    request_id=uuid4(),
                    query="fail",
                    game="dota2",
                )
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("runner failure should propagate")

        assert "failed" in calls
        assert "complete" not in calls

    asyncio.run(scenario())


def test_cache_failure_after_commit_does_not_mark_durable_run_failed() -> None:
    async def scenario() -> None:
        run_id = uuid4()
        session_id = uuid4()
        calls: list[str] = []
        run_repository = FakeRunRepository(calls=calls, run_id=run_id, session_id=session_id)
        executor = ChatRunExecutor(
            runner=FakeRunner(calls=calls),
            run_repository=run_repository,
            chat_repository=FakeChatRepository(calls=calls),
            session_store=FakeSessionStore(),
            memory_service=FakeMemoryService(
                calls=calls,
                record_error=SessionStoreError("unavailable"),
            ),
            event_bus=FakeEventBus([], calls),
            worker_id="worker-a",
            build_turn=lambda state: _build_turn(state),
            build_response=lambda state, sid: {"answer": "done"},
        )

        result = await executor.execute(
            ChatRunExecutionRequest(
                run_id=run_id,
                browser_id="browser-a",
                session_id=session_id,
                request_id=uuid4(),
                query="cache failure",
                game="dota2",
            )
        )

        assert result.run.status == "completed"
        assert run_repository.completed is not None
        assert run_repository.completed.status == "completed"
        assert "failed" not in calls

    asyncio.run(scenario())


def test_non_cache_exception_after_commit_does_not_mark_durable_run_failed() -> None:
    async def scenario() -> None:
        run_id = uuid4()
        session_id = uuid4()
        calls: list[str] = []
        run_repository = FakeRunRepository(calls=calls, run_id=run_id, session_id=session_id)
        executor = ChatRunExecutor(
            runner=FakeRunner(calls=calls),
            run_repository=run_repository,
            chat_repository=FakeChatRepository(calls=calls),
            session_store=FakeSessionStore(),
            memory_service=FakeMemoryService(
                calls=calls,
                record_error=RuntimeError("unexpected cache adapter failure"),
            ),
            event_bus=FakeEventBus([], calls),
            worker_id="worker-a",
            build_turn=lambda state: _build_turn(state),
            build_response=lambda state, sid: {"answer": "done"},
        )

        try:
            await executor.execute(
                ChatRunExecutionRequest(
                    run_id=run_id,
                    browser_id="browser-a",
                    session_id=session_id,
                    request_id=uuid4(),
                    query="post-commit failure",
                    game="dota2",
                )
            )
        except RuntimeError as exc:
            assert "unexpected cache adapter failure" in str(exc)
        else:
            raise AssertionError("post-commit infrastructure failure should propagate")

        assert run_repository.completed is not None
        assert run_repository.completed.status == "completed"
        assert "failed" not in calls

    asyncio.run(scenario())


def test_chat_run_executor_maps_task_cancel_to_interrupted_without_cancel_request() -> None:
    async def scenario() -> None:
        run_id = uuid4()
        session_id = uuid4()
        calls: list[str] = []
        runner = BlockingRunner()
        run_repository = FakeRunRepository(
            calls=calls,
            run_id=run_id,
            session_id=session_id,
            cancel_requested=False,
        )
        executor = ChatRunExecutor(
            runner=runner,
            run_repository=run_repository,
            chat_repository=FakeChatRepository(calls=calls),
            session_store=FakeSessionStore(),
            memory_service=FakeMemoryService(calls=calls),
            event_bus=FakeEventBus([], calls),
            worker_id="worker-a",
            build_turn=lambda state: _build_turn(state),
            build_response=lambda state, sid: {},
        )
        task = asyncio.create_task(
            executor.execute(
                ChatRunExecutionRequest(
                    run_id=run_id,
                    browser_id="browser-a",
                    session_id=session_id,
                    request_id=uuid4(),
                    query="cancel",
                    game="dota2",
                )
            )
        )
        await runner.started.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert "interrupted" in calls
        assert "cancelled" not in calls

    asyncio.run(scenario())


async def _build_turn(state: AgentRunState) -> TurnBuildResult:
    return TurnBuildResult(
        turn=Turn(query=state.query),
        assistant_message="done",
    )


class FakeRunner:
    def __init__(self, *, calls: list[str], failure: Exception | None = None) -> None:
        self.calls = calls
        self.failure = failure
        self.state_ids: list = []

    async def run(self, state: AgentRunState) -> AgentRunState:
        self.calls.append("graph")
        if self.failure is not None:
            raise self.failure
        assert state.internal_run_id is not None
        state.response = {"answer": "done"}
        state.status = "ok"
        self.state_ids.append(state.internal_run_id)
        return state


class BlockingRunner(FakeRunner):
    def __init__(self) -> None:
        super().__init__(calls=[])
        self.started = asyncio.Event()

    async def run(self, state: AgentRunState) -> AgentRunState:
        self.started.set()
        await asyncio.Event().wait()
        return state


class FakeEventBus:
    def __init__(self, events: list[StoredRunEvent], calls: list[str]) -> None:
        self.events = events
        self.calls = calls

    async def append(self, *, run_id, session_id, event: PlanStreamEvent) -> StoredRunEvent:
        stored = StoredRunEvent(
            run_id=run_id,
            session_id=session_id,
            sequence=len(self.events) + 1,
            event=event,
        )
        self.events.append(stored)
        self.calls.append(f"event:{event.type}")
        return stored


class FakeSessionStore:
    @asynccontextmanager
    async def transaction(self, session_id: str):
        yield

    def current_fencing_token(self, session_id: str) -> int:
        return 1


class FakeChatRepository:
    def __init__(self, *, calls: list[str]) -> None:
        self.calls = calls

    async def allocate_fencing_token(self, browser_id: str, session_id) -> int:
        self.calls.append("fencing")
        return 7



class FakeMemoryService:
    def __init__(self, *, calls: list[str], record_error: Exception | None = None) -> None:
        self.calls = calls
        self.record_error = record_error

    async def load_recent_messages(self, browser_id: str, session_id):
        self.calls.append("history")
        return [], 1

    async def record_committed_turn(self, browser_id: str, session_id, turn) -> None:
        self.calls.append("recent_dialogue")
        if self.record_error is not None:
            raise self.record_error


@dataclass
class FakeRunRepository:
    calls: list[str]
    run_id: object
    session_id: object
    cancel_requested: bool = True
    completed: ChatRunSummary | None = None

    async def mark_running(self, **kwargs) -> ChatRunSummary:
        self.calls.append("running")
        return self._summary("running")

    async def complete_with_turn(self, **kwargs) -> ChatRunSummary:
        self.calls.append("complete")
        self.completed = self._summary("completed")
        return self.completed

    async def mark_failed(self, **kwargs) -> ChatRunSummary:
        self.calls.append("failed")
        return self._summary("failed")

    async def mark_interrupted(self, **kwargs) -> ChatRunSummary:
        self.calls.append("interrupted")
        return self._summary("interrupted")

    async def mark_cancelled(self, **kwargs) -> ChatRunSummary:
        if not self.cancel_requested:
            raise ChatRunRepositoryError("not_requested")
        self.calls.append("cancelled")
        return self._summary("cancelled")

    def _summary(self, status: str) -> ChatRunSummary:
        return ChatRunSummary(
            run_id=self.run_id,
            session_id=self.session_id,
            request_id=uuid4(),
            payload_hash="hash",
            user_query="query",
            status=status,
            fencing_token=7,
            worker_id="worker-a",
            last_event_sequence=0,
            result_turn_id=uuid4() if status == "completed" else None,
            error_code=None,
            created_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
            heartbeat_at=datetime.now(UTC),
            cancel_requested_at=None,
            completed_at=(
                datetime.now(UTC)
                if status in {"completed", "failed", "interrupted"}
                else None
            ),
        )
