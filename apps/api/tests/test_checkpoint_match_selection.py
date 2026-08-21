from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from app.agentic.graph import AgentGraphRunner
from app.agentic.models import ExecutionPlan, ToolCall, ToolResult
from app.agentic.nodes.tools import tool_executor_node
from app.agentic.planning.controller import AgentControllerResult
from app.agentic.planning.decisions import ToolPlanDecision, resolve_required_evidence
from app.agentic.runtime.checkpoint import CheckpointSnapshot
from app.agentic.runtime.checkpoint_adapters import (
    apply_match_selection,
    match_selection_checkpoint,
)
from app.agentic.runtime.clock import FakeClock
from app.agentic.runtime.models import CachedToolCall, RunBudget, ToolDispatchRecord
from app.agentic.runtime.recovery import tool_call_fingerprint
from app.agentic.runtime.summaries import build_attempt_record, resolve_terminal_outcome
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolDefinition, ToolRegistry
from app.agentic.tools.executor import ToolExecutor
from app.agentic.tools.pandascore_tools import PandaScoreResolveMatchGamesInput
from app.application.chat_run_executor import ChatRunExecutionRequest, ChatRunExecutor
from app.application.chat_run_repository import ChatRunSummary


class EmptyInput(BaseModel):
    pass


class ResolveCompetitionInput(BaseModel):
    query: str


def test_match_selection_checkpoint_builds_options_and_patches_scheduled_date() -> None:
    result = ToolResult(
        tool_call_id="resolve_games",
        tool="pandascore.resolve_match_games",
        status="ok",
        data={
            "status": "ambiguous",
            "candidates": [
                {
                    "pandascore_match_id": 101,
                    "name": "TEAM VISION vs BoomBoys",
                    "scheduled_at": "2026-08-20T10:00:00Z",
                    "tournament": {"name": "Playoffs"},
                },
                {
                    "pandascore_match_id": 102,
                    "name": "TEAM VISION vs BoomBoys",
                    "scheduled_at": "2026-08-21T10:00:00Z",
                    "tournament": {"name": "Playoffs"},
                },
            ],
        },
        latency_ms=1,
    )

    checkpoint = match_selection_checkpoint(result)

    assert checkpoint is not None
    assert checkpoint.checkpoint_type == "pandascore_match_selection"
    assert checkpoint.source_tool_call_id == "resolve_games"
    assert checkpoint.resume_node == "tools"
    assert [option.value for option in checkpoint.options] == [
        {"pandascore_match_id": 101},
        {"pandascore_match_id": 102},
    ]

    plan = ExecutionPlan(
        intent="match_detail",
        goal="Read details",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(
                id="resolve_games",
                tool="pandascore.resolve_match_games",
                args={"series_id": 10828, "team_queries": ["TEAM VISION", "BoomBoys"]},
            )
        ],
    )
    patched = apply_match_selection(plan, checkpoint, checkpoint.options[0].id)

    assert patched.tool_calls[0].args["pandascore_match_id"] == 101
    assert "pandascore_match_id" not in plan.tool_calls[0].args


def test_match_selection_checkpoint_supports_same_date_candidates() -> None:
    result = ToolResult(
        tool_call_id="resolve_games",
        tool="pandascore.resolve_match_games",
        status="ok",
        data={
            "status": "ambiguous",
            "candidates": [
                {
                    "pandascore_match_id": 101,
                    "name": "TEAM VISION vs BoomBoys",
                    "scheduled_at": "2026-08-20T10:00:00Z",
                    "tournament": {"name": "Playoffs"},
                },
                {
                    "pandascore_match_id": 102,
                    "name": "TEAM VISION vs BoomBoys",
                    "scheduled_at": "2026-08-20T14:00:00Z",
                    "tournament": {"name": "Playoffs"},
                },
            ],
        },
        latency_ms=1,
    )

    checkpoint = match_selection_checkpoint(result)

    assert checkpoint is not None
    assert [option.id for option in checkpoint.options] == ["match_101", "match_102"]
    assert [option.value for option in checkpoint.options] == [
        {"pandascore_match_id": 101},
        {"pandascore_match_id": 102},
    ]


def test_ambiguous_match_stops_tools_before_downstream_calls() -> None:
    calls: list[str] = []

    async def resolve_games(args: BaseModel, context: Any) -> dict[str, Any]:
        calls.append("resolve_games")
        return {
            "status": "ambiguous",
            "candidates": [
                {
                    "pandascore_match_id": 101,
                    "name": "TEAM VISION vs BoomBoys",
                    "scheduled_at": "2026-08-20T10:00:00Z",
                    "tournament": {"name": "Playoffs"},
                },
                {
                    "pandascore_match_id": 102,
                    "name": "TEAM VISION vs BoomBoys",
                    "scheduled_at": "2026-08-21T10:00:00Z",
                    "tournament": {"name": "Playoffs"},
                },
            ],
        }

    async def downstream(args: BaseModel, context: Any) -> dict[str, Any]:
        calls.append("downstream")
        return {"status": "unexpected"}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="pandascore.resolve_match_games",
            description="Resolve PandaScore games.",
            input_model=PandaScoreResolveMatchGamesInput,
            handler=resolve_games,
        )
    )
    registry.register(
        ToolDefinition(
            name="debug.downstream",
            description="Should not run while paused.",
            input_model=EmptyInput,
            handler=downstream,
        )
    )
    plan = ExecutionPlan(
        intent="match_detail",
        goal="Read details",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(
                id="resolve_games",
                tool="pandascore.resolve_match_games",
                args={"series_id": 10828, "team_queries": ["TEAM VISION", "BoomBoys"]},
            ),
            ToolCall(id="downstream", tool="debug.downstream", args={}),
        ],
    )
    controller = AgentControllerResult(
        status="decided",
        reason="match plan",
        decision=ToolPlanDecision(kind="tool_plan", plan=plan),
        evidence_resolution=resolve_required_evidence(plan, registry),
    )

    state = asyncio.run(
        AgentGraphRunner(FakeController(controller), registry).run(
            AgentRunState(
                query="TEAM VISION vs BoomBoys details",
                game="dota2",
                internal_run_id=uuid4(),
            )
        )
    )

    assert state.status == "waiting_input"
    assert state.checkpoint is not None
    assert state.checkpoint.source_tool_call_id == "resolve_games"
    assert calls == ["resolve_games"]


def test_resume_state_patches_the_server_selected_date() -> None:
    result = ToolResult(
        tool_call_id="resolve_games",
        tool="pandascore.resolve_match_games",
        status="ok",
        data={
            "status": "ambiguous",
            "candidates": [
                {
                    "pandascore_match_id": 101,
                    "name": "TEAM VISION vs BoomBoys",
                    "scheduled_at": "2026-08-20T10:00:00Z",
                    "tournament": {"name": "Playoffs"},
                }
            ],
        },
        latency_ms=1,
    )
    checkpoint = match_selection_checkpoint(result)
    assert checkpoint is not None
    plan = ExecutionPlan(
        intent="match_detail",
        goal="Read details",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(
                id="resolve_games",
                tool="pandascore.resolve_match_games",
                args={"series_id": 10828, "team_queries": ["TEAM VISION", "BoomBoys"]},
            )
        ],
    )
    snapshot = CheckpointSnapshot(
        checkpoint=checkpoint,
        plan=plan,
        tool_results=[result],
        tool_dispatch_records=[
            ToolDispatchRecord(
                tool_call_id="resolve_games",
                tool="pandascore.resolve_match_games",
                handler_entered=True,
                stage="handler",
            )
        ],
        run_budget=RunBudget(),
        attempt_index=0,
        selected_option_id=checkpoint.options[0].id,
        executed_call_fingerprints={
            "ambiguous-games": CachedToolCall(
                call_id="resolve_games",
                result=result,
                dispatch=ToolDispatchRecord(
                    tool_call_id="resolve_games",
                    tool="pandascore.resolve_match_games",
                    handler_entered=True,
                    stage="handler",
                ),
            )
        },
    )
    run_id = uuid4()
    session_id = uuid4()
    now = datetime.now(UTC)
    running = ChatRunSummary(
        run_id=run_id,
        session_id=session_id,
        request_id=uuid4(),
        payload_hash="hash",
        user_query="match details",
        status="running",
        fencing_token=1,
        worker_id="worker-a",
        last_event_sequence=0,
        result_turn_id=None,
        error_code=None,
        created_at=now,
        started_at=now,
        heartbeat_at=now,
        cancel_requested_at=None,
        completed_at=None,
        checkpoint_state=snapshot.model_dump(mode="json"),
    )
    executor = ChatRunExecutor.__new__(ChatRunExecutor)
    executor._runner = SimpleNamespace(
        runtime_policy=SimpleNamespace(max_elapsed_seconds=60),
        clock=SimpleNamespace(monotonic=lambda: 1.0),
    )

    state = executor._state_from_checkpoint(
        request=ChatRunExecutionRequest(
            run_id=run_id,
            browser_id="browser-a",
            session_id=session_id,
            request_id=uuid4(),
            query="match details",
            game="dota2",
            resume=True,
        ),
        running=running,
        recent_messages=[],
        next_turn_index=1,
    )

    assert state.plan is not None
    assert state.plan.tool_calls[0].args["pandascore_match_id"] == 101
    assert state.tool_results == []
    assert state.tool_dispatch_records == []
    assert state.executed_call_fingerprints == {}


def _resumed_state_with_prefix() -> tuple[AgentRunState, datetime]:
    prefix_result = ToolResult(
        tool_call_id="resolve_comp",
        tool="debug.resolve_comp",
        status="ok",
        data={"series_id": 10828},
        latency_ms=1,
    )
    ambiguous_result = ToolResult(
        tool_call_id="resolve_games",
        tool="pandascore.resolve_match_games",
        status="ok",
        data={
            "status": "ambiguous",
            "candidates": [
                {
                    "pandascore_match_id": 101,
                    "name": "TEAM VISION vs BoomBoys",
                    "scheduled_at": "2026-08-20T10:00:00Z",
                    "tournament": {"name": "Playoffs"},
                },
                {
                    "pandascore_match_id": 102,
                    "name": "TEAM VISION vs BoomBoys",
                    "scheduled_at": "2026-08-21T10:00:00Z",
                    "tournament": {"name": "Playoffs"},
                },
            ],
        },
        latency_ms=1,
    )
    plan = ExecutionPlan(
        intent="match_detail",
        goal="Read details",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(
                id="resolve_comp",
                tool="debug.resolve_comp",
                args={"query": "The International"},
            ),
            ToolCall(
                id="resolve_games",
                tool="pandascore.resolve_match_games",
                args={
                    "series_id": "$resolve_comp.data.series_id",
                    "team_queries": ["TEAM VISION", "BoomBoys"],
                },
            ),
        ],
    )
    checkpoint = match_selection_checkpoint(ambiguous_result)
    assert checkpoint is not None
    prefix_dispatch = ToolDispatchRecord(
        tool_call_id="resolve_comp",
        tool="debug.resolve_comp",
        handler_entered=True,
        stage="handler",
    )
    ambiguous_dispatch = ToolDispatchRecord(
        tool_call_id="resolve_games",
        tool="pandascore.resolve_match_games",
        handler_entered=True,
        stage="handler",
    )
    prefix_fingerprint = tool_call_fingerprint(
        "debug.resolve_comp", {"query": "The International"}, plan.context
    )
    snapshot = CheckpointSnapshot(
        checkpoint=checkpoint,
        plan=plan,
        tool_results=[prefix_result, ambiguous_result],
        tool_dispatch_records=[prefix_dispatch, ambiguous_dispatch],
        run_budget=RunBudget(),
        attempt_index=0,
        selected_option_id=checkpoint.options[0].id,
        executed_call_fingerprints={
            prefix_fingerprint: CachedToolCall(
                call_id="resolve_comp",
                result=prefix_result,
                dispatch=prefix_dispatch,
            ),
            "ambiguous-games": CachedToolCall(
                call_id="resolve_games",
                result=ambiguous_result,
                dispatch=ambiguous_dispatch,
            ),
        },
    )
    run_id = uuid4()
    session_id = uuid4()
    now = datetime.now(UTC)
    running = ChatRunSummary(
        run_id=run_id,
        session_id=session_id,
        request_id=uuid4(),
        payload_hash="hash",
        user_query="match details",
        status="running",
        fencing_token=1,
        worker_id="worker-a",
        last_event_sequence=0,
        result_turn_id=None,
        error_code=None,
        created_at=now,
        started_at=now,
        heartbeat_at=now,
        cancel_requested_at=None,
        completed_at=None,
        checkpoint_state=snapshot.model_dump(mode="json"),
    )
    executor = ChatRunExecutor.__new__(ChatRunExecutor)
    executor._runner = SimpleNamespace(
        runtime_policy=SimpleNamespace(max_elapsed_seconds=60),
        clock=SimpleNamespace(monotonic=lambda: 1.0),
    )

    state = executor._state_from_checkpoint(
        request=ChatRunExecutionRequest(
            run_id=run_id,
            browser_id="browser-a",
            session_id=session_id,
            request_id=uuid4(),
            query="match details",
            game="dota2",
            resume=True,
        ),
        running=running,
        recent_messages=[],
        next_turn_index=1,
    )
    return state, now


def test_resume_state_keeps_only_prefix_fingerprints() -> None:
    state, _now = _resumed_state_with_prefix()
    assert state.plan is not None
    assert state.plan.tool_calls[1].args["pandascore_match_id"] == 101
    assert state.tool_results == []
    assert state.tool_dispatch_records == []
    assert {
        cached.call_id for cached in state.executed_call_fingerprints.values()
    } == {"resolve_comp"}


def test_resumed_tools_emit_fresh_records_and_build_attempt_summary() -> None:
    state, now = _resumed_state_with_prefix()

    async def resolve_comp(args: BaseModel, context: Any) -> dict[str, Any]:
        raise AssertionError("prefix call must be reused from the fingerprint cache")

    async def resolve_games(args: BaseModel, context: Any) -> dict[str, Any]:
        assert args.pandascore_match_id == 101
        assert args.series_id == 10828
        return {"status": "resolved", "resolution_inputs": [{"pandascore_match_id": 101}]}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="debug.resolve_comp",
            description="Resolve competition.",
            input_model=ResolveCompetitionInput,
            handler=resolve_comp,
        )
    )
    registry.register(
        ToolDefinition(
            name="pandascore.resolve_match_games",
            description="Resolve games.",
            input_model=PandaScoreResolveMatchGamesInput,
            handler=resolve_games,
        )
    )

    state = asyncio.run(tool_executor_node(state, ToolExecutor(registry), FakeClock(now)))

    assert [result.tool_call_id for result in state.tool_results] == [
        "resolve_comp",
        "resolve_games",
    ]
    assert [record.tool_call_id for record in state.tool_dispatch_records] == [
        "resolve_comp",
        "resolve_games",
    ]
    assert [record.stage for record in state.tool_dispatch_records] == [
        "cache_reuse",
        "handler",
    ]
    attempt = build_attempt_record(
        state,
        resolve_terminal_outcome(state),
        duration_ms=1,
    )
    assert [call.tool_call_id for call in attempt.tool_calls] == [
        "resolve_comp",
        "resolve_games",
    ]


class FakeController:
    def __init__(self, result: AgentControllerResult) -> None:
        self.result = result

    @property
    def prompt_versions(self) -> dict[str, str]:
        return {}

    async def decide(self, query: str, game: str = "dota2", history=None, **kwargs):
        return self.result
