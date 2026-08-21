import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from app.agentic.answer import AnswerSynthesisResult
from app.agentic.conversation.models import ConversationMessage
from app.agentic.critic import AgenticCriticReview
from app.agentic.evidence import EvidenceDataQuality, EvidenceGraph
from app.agentic.graph import AgentGraphRunner, _route_after_evidence
from app.agentic.models import ExecutionPlan, QueryContext, ToolCall, ToolResult, ToolSource
from app.agentic.nodes import (
    attempt_finalize_node,
    evidence_node,
    response_node,
    run_finalize_node,
    run_init_node,
)
from app.agentic.planning.controller import AgentControllerResult
from app.agentic.planning.decisions import (
    CapabilityBoundaryDecision,
    DirectAnswerResult,
    ToolPlanDecision,
    resolve_required_evidence,
)
from app.agentic.runtime import (
    AttemptAnswerSummary,
    FakeClock,
    RecoveryFeedback,
    RunBudget,
    RunContext,
    ToolDispatchRecord,
)
from app.agentic.runtime.reset import reset_attempt_working_state
from app.agentic.runtime.summaries import resolve_terminal_outcome
from app.agentic.state import AgentRunState, AgentTraceEvent
from app.agentic.tools import ToolDefinition, ToolExecutor, ToolRegistry
from app.core.config import RuntimePolicy

UTC_START = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)
SENTINEL = "PRIVATE_SENTINEL_7dcd"


class RequiredText(BaseModel):
    value: str


def test_run_context_budget_and_fake_clock_contracts() -> None:
    clock = FakeClock(UTC_START, 10.0)
    state = AgentRunState(query="q", game="dota2")

    run_init_node(state, RuntimePolicy(max_elapsed_seconds=60), clock)

    assert state.run_context is not None
    assert state.run_context.run_id.version == 4
    assert state.run_context.request_id is None
    assert state.run_context.session_id is None
    assert state.run_context.started_at == UTC_START
    assert state.run_context.deadline_at == UTC_START + timedelta(seconds=60)
    assert state.run_context.prompt_versions == {}
    assert state.run_budget is not None
    assert state.run_budget.remaining("tools") == 16
    assert not state.run_budget.deadline_exceeded(clock.monotonic() - 10.0)
    with pytest.raises(RuntimeError, match="run context already exists"):
        run_init_node(state, RuntimePolicy(), clock)

    # deadline_at is audit-only: a wall-clock jump cannot create elapsed timeout.
    clock.current_utc += timedelta(hours=2)
    assert clock.now_utc() > state.run_context.deadline_at
    assert not state.run_budget.deadline_exceeded(clock.monotonic() - 10.0)
    clock.advance(60)
    assert state.run_budget.deadline_exceeded(clock.monotonic() - 10.0)


def test_runtime_models_are_strict_and_limit_recovery_to_attempts() -> None:
    with pytest.raises(ValidationError):
        AttemptAnswerSummary(
            answer_type="direct_answer",
            status="ok",
            confidence=None,
            hidden=SENTINEL,
        )
    with pytest.raises(ValidationError):
        RunContext(
            run_id=uuid4(),
            started_at=datetime(2026, 7, 20),
            deadline_at=UTC_START,
        )

    assert "recovery_reason" not in RunContext.model_fields
    assert "recovery_code" not in RunContext.model_fields
    from app.agentic.runtime import AttemptRecord

    assert "recovery_reason" not in AttemptRecord.model_fields
    assert "recovery_code" in AttemptRecord.model_fields


def test_budget_records_over_limit_without_enforcement() -> None:
    budget = RunBudget(max_tool_calls_total=1)

    budget.record_tool_call()
    budget.record_tool_call()

    assert budget.tool_calls_used == 2
    assert budget.remaining("tools") == 0
    assert budget.exhausted("tools")


def test_reset_attempt_state_is_pure_clears_work_and_detaches_mutables() -> None:
    clock = FakeClock(UTC_START, 3.0)
    state = AgentRunState(
        query="keep query",
        game="dota2",
        recent_messages=[ConversationMessage(turn_index=1, role="user", content="keep history")],
        internal_session_id=uuid4(),
        decision_kind="tool_plan",
        missing_fields=["hero_query"],
        plan=_private_plan(),
        planner_required_evidence=["kind"],
        global_required_evidence=["kind"],
        effective_required_evidence=["kind"],
        required_evidence_sources={"kind": ["planner"]},
        mandatory_evidence_by_call={"call": ["kind"]},
        tool_results=[_private_tool_result()],
        tool_dispatch_records=[_private_dispatch()],
        answer=_private_answer(),
        review=_private_review(),
        validation_failed=True,
        safe_failure_required=True,
        status="error",
        reason="clear reason",
        errors=["clear error"],
        response_type="tool_error",
        response={"clear": True},
        terminal_stage="critic",
        run_duration_ms=123,
        trace=[AgentTraceEvent(node="old", action="keep trace", status="completed")],
        recovery_action="replan",
        recovery_feedback=RecoveryFeedback(
            missing_evidence=["kind"],
            remaining_tool_budget=2,
        ),
        recovery_baseline_decision=ToolPlanDecision(
            kind="tool_plan",
            plan=_private_plan(),
        ),
    )
    run_init_node(state, RuntimePolicy(), clock)
    original = state.model_copy(deep=True)

    reset = reset_attempt_working_state(
        state,
        next_attempt_index=1,
        started_at=UTC_START + timedelta(seconds=2),
        started_monotonic=5.0,
    )

    assert state == original
    assert reset.query == state.query
    assert reset.game == state.game
    assert reset.recent_messages == state.recent_messages
    assert reset.internal_session_id == state.internal_session_id
    assert reset.run_started_monotonic == state.run_started_monotonic
    assert reset.attempt_index == 1
    assert reset.attempt_started_monotonic == 5.0
    assert reset.controller_result is None
    assert reset.decision is None
    assert reset.decision_kind is None
    assert reset.plan is None
    assert reset.tool_results == []
    assert reset.tool_dispatch_records == []
    assert reset.evidence_graph is None
    assert reset.answer is None
    assert reset.review is None
    assert reset.missing_fields == []
    assert reset.effective_required_evidence == []
    assert reset.required_evidence_sources == {}
    assert reset.status == "error"
    assert reset.reason == ""
    assert reset.errors == []
    assert reset.response is None
    assert reset.terminal_stage is None
    assert reset.run_duration_ms is None
    assert reset.recovery_action is None
    assert reset.recovery_feedback == state.recovery_feedback
    assert reset.recovery_feedback is not state.recovery_feedback
    assert reset.recovery_baseline_decision == state.recovery_baseline_decision
    assert reset.recovery_baseline_decision is not state.recovery_baseline_decision

    assert reset.run_budget is not state.run_budget
    assert reset.recent_messages is not state.recent_messages
    assert reset.attempts is not state.attempts
    assert reset.trace is not state.trace
    assert reset.run_budget is not None and state.run_budget is not None
    reset.run_budget.record_tool_call()
    reset.recent_messages.append(
        ConversationMessage(turn_index=1, role="assistant", content="new")
    )
    reset.trace.append(AgentTraceEvent(node="new", action="new", status="planned"))
    assert state.run_budget.tool_calls_used == 0
    assert len(state.recent_messages) == 1
    assert len(state.trace) == 3


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("conversation", ("ok", "direct_answer", "ok", "conversation_answer", None)),
        (
            "clarification",
            (
                "clarification_required",
                "clarification",
                "clarification_required",
                "decision_validation",
                None,
            ),
        ),
        (
            "context",
            (
                "insufficient_context",
                "conversation_context_missing",
                "insufficient_context",
                "decision_validation",
                None,
            ),
        ),
        (
            "capability",
            (
                "insufficient_tools",
                "capability_boundary",
                "insufficient_tools",
                "decision_validation",
                None,
            ),
        ),
        ("success", ("ok", "natural_language_answer", "ok", "critic", None)),
        ("controller", ("error", "planning_error", "error", "controller", "controller")),
        (
            "controller_validation",
            (
                "error",
                "decision_validation_error",
                "error",
                "controller",
                "decision_validation",
            ),
        ),
        (
            "decision_validation",
            (
                "error",
                "decision_validation_error",
                "error",
                "decision_validation",
                "decision_validation",
            ),
        ),
        (
            "plan_validation",
            (
                "error",
                "decision_validation_error",
                "error",
                "plan_validation",
                "plan_validation",
            ),
        ),
        (
            "conversation_validation",
            (
                "error",
                "decision_validation_error",
                "error",
                "conversation_answer",
                "conversation_answer",
            ),
        ),
        ("tool", ("error", "tool_error", "error", "tool_execution", "tool_execution")),
        ("answer", ("error", "answer_error", "error", "answer", "answer")),
        (
            "evidence",
            (
                "insufficient_evidence",
                "insufficient_evidence",
                "insufficient_evidence",
                "evidence",
                "evidence",
            ),
        ),
        (
            "critic",
            (
                "insufficient_evidence",
                "insufficient_evidence",
                "insufficient_evidence",
                "critic",
                "critic",
            ),
        ),
        ("execution", ("error", "execution_error", "error", "execution", "execution")),
    ],
)
def test_terminal_outcome_table(case: str, expected: tuple) -> None:
    outcome = resolve_terminal_outcome(_terminal_state(case))

    assert (
        outcome.public_status,
        outcome.response_type,
        outcome.attempt_status,
        outcome.terminal_stage,
        outcome.failure_stage,
    ) == expected


def test_executor_dispatch_channel_counts_only_handler_entry() -> None:
    budget = RunBudget(max_tool_calls_total=1)
    registry = ToolRegistry()

    async def fail_async(args: RequiredText, context: QueryContext) -> None:
        raise RuntimeError(f"async boom: {args.value}")

    registry.register(
        ToolDefinition(
            name="ok",
            description="ok",
            input_model=RequiredText,
            handler=lambda args, context: {"value": args.value},
        )
    )
    registry.register(
        ToolDefinition(
            name="fail",
            description="fail",
            input_model=RequiredText,
            handler=lambda args, context: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    )
    registry.register(
        ToolDefinition(
            name="async_fail",
            description="async fail",
            input_model=RequiredText,
            handler=fail_async,
        )
    )
    executor = ToolExecutor(registry)

    unknown, unknown_dispatch = asyncio.run(
        executor.execute(
            ToolCall(id="unknown", tool="missing", args={}),
            QueryContext(),
            on_handler_entered=budget.record_tool_call,
        )
    )
    invalid, invalid_dispatch = asyncio.run(
        executor.execute(
            ToolCall(id="invalid", tool="ok", args={}),
            QueryContext(),
            on_handler_entered=budget.record_tool_call,
        )
    )
    failed, failed_dispatch = asyncio.run(
        executor.execute(
            ToolCall(id="failed", tool="fail", args={"value": "x"}),
            QueryContext(),
            on_handler_entered=budget.record_tool_call,
        )
    )
    succeeded, success_dispatch = asyncio.run(
        executor.execute(
            ToolCall(id="ok", tool="ok", args={"value": "x"}),
            QueryContext(),
            on_handler_entered=budget.record_tool_call,
        )
    )
    async_failed, async_failed_dispatch = asyncio.run(
        executor.execute(
            ToolCall(id="async-failed", tool="async_fail", args={"value": "x"}),
            QueryContext(),
            on_handler_entered=budget.record_tool_call,
        )
    )

    assert unknown.status == invalid.status == failed.status == async_failed.status == "error"
    assert succeeded.status == "ok"
    assert unknown_dispatch.model_dump() == {
        "tool_call_id": "unknown",
        "tool": "missing",
        "handler_entered": False,
        "stage": "pre_dispatch",
        "error_code": "tool_not_registered",
    }
    assert invalid_dispatch.error_code == "input_validation_error"
    assert not invalid_dispatch.handler_entered
    assert failed_dispatch.error_code == "handler_error"
    assert failed_dispatch.handler_entered
    assert success_dispatch.error_code is None
    assert success_dispatch.handler_entered
    assert async_failed_dispatch.error_code == "handler_error"
    assert async_failed_dispatch.handler_entered
    assert budget.tool_calls_used == 3
    assert "stage" not in failed.metadata
    assert "error_code" not in failed.metadata


def test_attempt_and_public_runtime_do_not_leak_private_payloads() -> None:
    clock = FakeClock(UTC_START, 0)
    state = AgentRunState(
        query="safe query",
        game="dota2",
        decision_kind="tool_plan",
        plan=_private_plan(),
        effective_required_evidence=["kind"],
        tool_results=[_private_tool_result()],
        tool_dispatch_records=[_private_dispatch()],
        answer=_private_answer(),
        review=_private_review(),
        status="error",
        reason="ordinary reason",
    )
    run_init_node(state, RuntimePolicy(), clock)
    clock.advance(0.125)
    attempt_finalize_node(state, clock)
    run_finalize_node(state, clock)
    response_node(state)

    attempt_json = state.attempts[0].model_dump_json()
    runtime_json = str(state.response["runtime"])
    trace_json = str(state.response["trace"])
    assert SENTINEL not in attempt_json
    assert SENTINEL not in runtime_json
    assert SENTINEL not in trace_json
    assert "handler_entered" in runtime_json
    assert "dispatch_stage" in runtime_json
    assert "failure_code" in runtime_json
    tool_status = state.response["runtime"]["attempts"][0]["tool_call_statuses"][0]
    assert tool_status["handler_entered"] is True
    assert tool_status["dispatch_stage"] == "handler"
    assert tool_status["failure_code"] == "handler_error"
    assert "error_code" not in runtime_json
    assert state.response["tool_results"][0]["error"] == "tool execution failed"


def test_safe_failure_runtime_is_minimal_and_sanitized() -> None:
    clock = FakeClock(UTC_START, 0)
    state = AgentRunState(
        query="safe query",
        game="dota2",
        controller_result=AgentControllerResult(
            status="error",
            reason="controller failed",
            failure_type="planning_error",
            errors=[SENTINEL],
            raw_content=SENTINEL,
        ),
        plan=_private_plan(),
        safe_failure_required=True,
        status="error",
        errors=[SENTINEL],
    )
    run_init_node(state, RuntimePolicy(), clock)
    attempt_finalize_node(state, clock)
    run_finalize_node(state, clock)
    response_node(state)

    response_json = str(state.response)
    attempt = state.response["runtime"]["attempts"][0]
    assert SENTINEL not in response_json
    assert attempt["decision_kind"] is None
    assert attempt["tool_call_statuses"] == []
    assert attempt["evidence_summary"] is None
    assert attempt["answer_summary"] is None
    assert attempt["critic_summary"] is None


def test_graph_trace_has_two_events_per_node_and_injected_timing() -> None:
    clock = FakeClock(UTC_START, 1.0)

    class AdvancingController:
        @property
        def prompt_versions(self) -> dict[str, str]:
            return {}

        async def decide(self, query: str, game: str = "dota2", history=None, **kwargs):
            clock.advance(0.25)
            return AgentControllerResult(
                status="decided",
                reason="unsupported",
                decision=CapabilityBoundaryDecision(
                    kind="capability_boundary",
                    intent="unsupported",
                    reason="unsupported",
                ),
            )

    state = asyncio.run(
        AgentGraphRunner(AdvancingController(), ToolRegistry(), clock=clock).run(
            AgentRunState(query="q", game="dota2")
        )
    )

    grouped = {}
    for event in state.trace:
        grouped.setdefault(event.node, []).append(event)
        assert event.run_id == state.run_context.run_id
        assert event.attempt_index == 0
        assert event.started_at is not None
    assert "response" not in grouped
    assert set(grouped) == {
        "run_init",
        "controller",
        "decision_validate",
        "attempt_finalize",
        "recovery",
        "run_finalize",
    }
    assert all(
        [event.status for event in events] == ["planned", "completed"]
        for events in grouped.values()
    )
    assert all(events[0].duration_ms == 0 for events in grouped.values())
    assert grouped["controller"][1].duration_ms == 250
    assert len(state.attempts) == 1
    assert state.run_budget.controller_calls_used == 1
    assert state.run_budget.replans_used == 0


def test_trace_status_rejects_business_severity_values() -> None:
    with pytest.raises(ValidationError):
        AgentTraceEvent(node="critic", action="review", status="warning")


def test_missing_evidence_plan_is_execution_error_not_raw_success() -> None:
    clock = FakeClock(UTC_START, 0)
    state = AgentRunState(query="q", game="dota2", status="ok")
    run_init_node(state, RuntimePolicy(), clock)

    evidence_node(state, ToolRegistry())

    assert state.status == "error"
    assert state.errors == ["missing execution plan for evidence construction"]
    assert _route_after_evidence(state) == "response"
    attempt_finalize_node(state, clock)
    run_finalize_node(state, clock)
    response_node(state)
    assert state.response["status"] == "error"
    assert state.response["response_type"] == "execution_error"
    assert state.response["runtime"]["terminal_stage"] == "execution"
    assert [event.status for event in state.trace if event.node == "evidence"] == [
        "planned",
        "failed",
    ]


@pytest.mark.parametrize(
    ("answer_status", "public_status", "terminal_stage"),
    [
        ("error", "error", "answer"),
        ("insufficient_evidence", "insufficient_evidence", "evidence"),
    ],
)
def test_failed_answer_skips_critic_and_emits_failed_trace(
    answer_status: str,
    public_status: str,
    terminal_stage: str,
) -> None:
    runner = _answer_graph_runner(answer_status=answer_status, confidence=0)

    state = asyncio.run(runner.run(AgentRunState(query="q", game="dota2")))

    assert state.status == public_status
    assert state.terminal_stage == terminal_stage
    assert state.review is None
    assert state.attempts[0].critic_summary is None
    assert [event.status for event in state.trace if event.node == "answer"] == [
        "planned",
        "failed",
    ]
    assert all(event.node != "critic" for event in state.trace)


@pytest.mark.parametrize(
    ("confidence", "severity"),
    [(0.8, "pass"), (0.45, "warning")],
)
def test_critic_pass_and_warning_emit_completed_trace(
    confidence: float,
    severity: str,
) -> None:
    runner = _answer_graph_runner(answer_status="ok", confidence=confidence)

    state = asyncio.run(runner.run(AgentRunState(query="q", game="dota2")))

    assert state.status == "ok"
    assert state.review is not None
    assert state.review.severity == severity
    assert [event.status for event in state.trace if event.node == "critic"] == [
        "planned",
        "completed",
    ]


def _answer_graph_runner(*, answer_status: str, confidence: float) -> AgentGraphRunner:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="debug.echo",
            description="Echo a value.",
            input_model=RequiredText,
            handler=lambda args, context: {"value": args.value},
        )
    )
    plan = ExecutionPlan(
        intent="debug",
        goal="Exercise Answer and Critic routing.",
        output_contract="natural_language_answer",
        tool_calls=[ToolCall(id="echo", tool="debug.echo", args={"value": "x"})],
    )

    class Controller:
        @property
        def prompt_versions(self) -> dict[str, str]:
            return {}

        async def decide(self, query: str, game: str = "dota2", history=None, **kwargs):
            return AgentControllerResult(
                status="decided",
                reason="test plan",
                decision=ToolPlanDecision(kind="tool_plan", plan=plan),
                evidence_resolution=resolve_required_evidence(plan, registry),
            )

    class Synthesizer:
        async def synthesize(self, execution_plan, graph, *, current_query=None):
            assert current_query == "q"
            return AnswerSynthesisResult(
                answer_type="natural_language_answer",
                status=answer_status,
                summary="answer",
                confidence=confidence,
            )

    runner = AgentGraphRunner(Controller(), registry, clock=FakeClock(UTC_START, 0))
    runner.answer_synthesizer = Synthesizer()
    return runner


def _terminal_state(case: str) -> AgentRunState:
    state = AgentRunState(query="q", game="dota2", status="ok", reason="reason")
    if case == "conversation":
        state.answer = DirectAnswerResult(summary="social")
    elif case == "clarification":
        state.status = "clarification_required"
    elif case == "context":
        state.status = "insufficient_context"
    elif case == "capability":
        state.status = "insufficient_tools"
    elif case == "success":
        state.answer = _private_answer(summary="public")
        state.review = AgenticCriticReview(passed=True, severity="pass")
    elif case in {"controller", "controller_validation"}:
        failure_type = (
            "decision_validation_error" if case == "controller_validation" else "planning_error"
        )
        state.controller_result = AgentControllerResult(
            status="error",
            reason="failed",
            failure_type=failure_type,
        )
    elif case in {"decision_validation", "plan_validation", "conversation_validation"}:
        stage = {
            "decision_validation": "decision_validation",
            "plan_validation": "plan_validation",
            "conversation_validation": "conversation_answer",
        }[case]
        state.validation_failed = True
        state.attempt_failure_stage = stage
        state.status = "error"
    elif case == "tool":
        state.tool_results = [_private_tool_result()]
        state.status = "error"
    elif case == "answer":
        state.answer = _private_answer(status="error")
        state.status = "error"
    elif case == "evidence":
        state.evidence_graph = EvidenceGraph(
            intent="i",
            required_evidence=["kind"],
            missing=["kind"],
            data_quality=EvidenceDataQuality(completeness=0),
        )
    elif case == "critic":
        state.review = AgenticCriticReview(
            passed=False,
            severity="failed",
            reasons=["bad"],
        )
    elif case == "execution":
        state.status = "error"
    return state


def _private_plan() -> ExecutionPlan:
    return ExecutionPlan(
        intent="private-intent",
        goal=SENTINEL,
        output_contract="natural_language_answer",
        context=QueryContext(bracket=[SENTINEL]),
        tool_calls=[ToolCall(id="call", tool="private.tool", args={"value": SENTINEL})],
        metadata={"private": SENTINEL},
    )


def _private_tool_result() -> ToolResult:
    return ToolResult(
        tool_call_id="call",
        tool="private.tool",
        status="error",
        data={"private": SENTINEL},
        source=ToolSource(name="private", kind="live", url=SENTINEL),
        latency_ms=7,
        error=SENTINEL,
        metadata={"private": SENTINEL},
    )


def _private_dispatch() -> ToolDispatchRecord:
    return ToolDispatchRecord(
        tool_call_id="call",
        tool="private.tool",
        handler_entered=True,
        stage="handler",
        error_code="handler_error",
    )


def _private_answer(*, status: str = "ok", summary: str = SENTINEL) -> AnswerSynthesisResult:
    return AnswerSynthesisResult(
        answer_type="natural_language_answer",
        status=status,
        summary=summary,
        confidence=0.8,
    )


def _private_review() -> AgenticCriticReview:
    return AgenticCriticReview(
        passed=False,
        severity="failed",
        reasons=[SENTINEL],
        metadata={"private": SENTINEL},
    )
