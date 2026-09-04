from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from app.agentic.models import ExecutionPlan
from app.agentic.runtime.checkpoint import Checkpoint, CheckpointOption
from app.agentic.runtime.models import RunBudget
from app.agentic.runtime.streaming import PlanStreamEvent
from app.agentic.state import AgentRunState
from app.application.chat_run_executor import ChatRunExecutionRequest, ChatRunExecutor
from app.application.chat_run_repository import ChatRunSummary
from app.application.run_event_bus import StoredRunEvent


def test_executor_persists_checkpoint_and_stops_without_turn() -> None:
    async def scenario() -> None:
        run_id = uuid4()
        session_id = uuid4()
        events: list[StoredRunEvent] = []
        repository = PauseRepository(run_id=run_id, session_id=session_id)
        executor = ChatRunExecutor(
            runner=PauseRunner(),
            run_repository=repository,
            chat_repository=FakeChatRepository(),
            session_store=FakeSessionStore(),
            memory_service=FakeMemoryService(),
            event_bus=FakeEventBus(events),
            worker_id="worker-a",
            build_turn=_unexpected_turn,
            build_response=lambda state, session_id: {},
        )

        result = await executor.execute(
            ChatRunExecutionRequest(
                run_id=run_id,
                browser_id="browser-a",
                session_id=session_id,
                request_id=uuid4(),
                query="match details",
                game="dota2",
            )
        )

        assert result.run.status == "waiting_input"
        assert repository.snapshot is not None
        assert "complete" not in repository.calls
        assert [event.event.type for event in events] == [
            "status",
            "checkpoint",
            "status",
        ]
        assert events[-1].event.status == "waiting_input"

    asyncio.run(scenario())


async def _unexpected_turn(state: AgentRunState):
    raise AssertionError("a paused Run must not build a Turn")


class PauseRunner:
    async def run(self, state: AgentRunState) -> AgentRunState:
        state.plan = ExecutionPlan(
            intent="match_detail",
            goal="Read match details",
            output_contract="natural_language_answer",
        )
        state.run_budget = RunBudget()
        state.checkpoint = Checkpoint(
            checkpoint_type="selection",
            question="请选择比赛。",
            source_tool_call_id="resolve_games",
            resume_node="tools",
            options=[
                CheckpointOption(
                    id="playoffs_2026_08_20",
                    label="8 月 20 日 · Playoffs",
                    value={"scheduled_date": "2026-08-20"},
                )
            ],
        )
        state.status = "waiting_input"
        return state


class FakeSessionStore:
    @asynccontextmanager
    async def transaction(self, session_id: str):
        yield

    def current_fencing_token(self, session_id: str) -> int:
        return 1


class FakeChatRepository:
    async def allocate_fencing_token(self, browser_id: str, session_id) -> int:
        return 7


class FakeMemoryService:
    async def load_recent_messages(self, browser_id: str, session_id):
        return [], 1

    async def record_committed_turn(self, browser_id: str, session_id, turn) -> None:
        raise AssertionError("a paused Run must not commit a Turn")


class FakeEventBus:
    def __init__(self, events: list[StoredRunEvent]) -> None:
        self.events = events

    async def append(self, *, run_id, session_id, event: PlanStreamEvent) -> StoredRunEvent:
        stored = StoredRunEvent(
            run_id=run_id,
            session_id=session_id,
            sequence=len(self.events) + 1,
            event=event,
        )
        self.events.append(stored)
        return stored


class PauseRepository:
    def __init__(self, *, run_id, session_id) -> None:
        self.run_id = run_id
        self.session_id = session_id
        self.calls: list[str] = []
        self.snapshot: dict | None = None

    async def mark_running(self, **kwargs) -> ChatRunSummary:
        self.calls.append("running")
        return self._summary("running")

    async def mark_waiting_input(self, *, checkpoint_state: dict, **kwargs) -> ChatRunSummary:
        self.calls.append("waiting_input")
        self.snapshot = checkpoint_state
        return self._summary("waiting_input")

    async def mark_failed(self, **kwargs) -> ChatRunSummary:
        self.calls.append("failed")
        return self._summary("failed")

    def _summary(self, status: str) -> ChatRunSummary:
        now = datetime.now(UTC)
        return ChatRunSummary(
            run_id=self.run_id,
            session_id=self.session_id,
            request_id=uuid4(),
            payload_hash="hash",
            user_query="match details",
            status=status,
            fencing_token=7 if status == "running" else None,
            worker_id="worker-a" if status == "running" else None,
            last_event_sequence=0,
            result_turn_id=None,
            error_code=None,
            created_at=now,
            started_at=now,
            heartbeat_at=now if status == "running" else None,
            cancel_requested_at=None,
            completed_at=None,
        )
