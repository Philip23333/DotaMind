import asyncio
from collections.abc import Callable
from datetime import datetime, timezone

import pytest
from pydantic import BaseModel

from app.agentic.answer import AnswerSynthesisResult
from app.agentic.evidence import EvidenceDataQuality, EvidenceGraph, EvidenceItem
from app.agentic.graph import AgentGraphRunner
from app.agentic.models import ExecutionPlan, QueryContext, ToolCall, ToolSource
from app.agentic.nodes import (
    attempt_finalize_node,
    attempt_reset_node,
    recovery_node,
    run_init_node,
    tool_executor_node,
)
from app.agentic.planning.controller import AgentControllerResult
from app.agentic.planning.decisions import ToolPlanDecision
from app.agentic.planning.recovery import validate_replan_decision
from app.agentic.runtime.clock import FakeClock
from app.agentic.runtime.models import RecoveryFeedback
from app.agentic.runtime.recovery import (
    recoverable_missing_evidence,
    tool_call_fingerprint,
)
from app.agentic.runtime.reset import reset_attempt_working_state
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolDefinition, ToolExecutor, ToolRegistry
from app.core.config import RuntimePolicy

UTC_START = datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc)


class ValueInput(BaseModel):
    value: int = 1


class SequenceController:
    def __init__(self, *decisions: ToolPlanDecision) -> None:
        self.decisions = list(decisions)
        self.calls: list[dict] = []

    @property
    def prompt_versions(self) -> dict[str, str]:
        return {"controller.recovery_rules": "v1"}

    async def decide(self, query, game="dota2", history=None, **kwargs):
        self.calls.append(kwargs)
        decision = self.decisions.pop(0).model_copy(deep=True)
        return AgentControllerResult(
            status="decided",
            reason="decision accepted",
            decision=decision,
        )


class FixedAnswerSynthesizer:
    async def synthesize(self, plan, graph, *, current_query=None):
        return AnswerSynthesisResult(
            answer_type=plan.output_contract,
            status="ok",
            summary="complete",
            confidence=1,
        )


def _evidence(kind: str) -> Callable:
    def extractor(result):
        return [
            EvidenceItem(
                id=f"{result.tool_call_id}:{kind}",
                kind=kind,
                subject="fixture",
                value={"kind": kind},
                tool_call_id=result.tool_call_id,
                tool=result.tool,
            )
        ]

    return extractor


def _empty_evidence(_result):
    return []


def _registry(
    calls: list[str],
    *,
    include_producer: bool = True,
    producer_emits: bool = True,
) -> ToolRegistry:
    source = ToolSource(name="UnitTest", kind="fixture")
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="debug.base",
            description="Return base data while declaring sample capability.",
            input_model=ValueInput,
            handler=lambda args, context: calls.append("base") or {"value": args.value},
            source=source,
            evidence_extractor=_evidence("base"),
            evidence_kinds=("base", "sample_size"),
        )
    )
    if include_producer:
        registry.register(
            ToolDefinition(
                name="debug.sample",
                description="Return the missing sample evidence.",
                input_model=ValueInput,
                handler=lambda args, context: calls.append("sample")
                or {"value": args.value},
                source=source,
                evidence_extractor=(
                    _evidence("sample_size") if producer_emits else _empty_evidence
                ),
                evidence_kinds=("sample_size",),
            )
        )
    registry.register(
        ToolDefinition(
            name="debug.other",
            description="Return unrelated data.",
            input_model=ValueInput,
            handler=lambda args, context: {"value": args.value},
        )
    )
    return registry


def _decision(*, recovered: bool = False) -> ToolPlanDecision:
    calls = [ToolCall(id="base", tool="debug.base", args={"value": 1})]
    if recovered:
        calls.append(ToolCall(id="sample", tool="debug.sample", args={"value": 2}))
    return ToolPlanDecision(
        kind="tool_plan",
        plan=ExecutionPlan(
            intent="fixture",
            goal="Collect the required sample evidence.",
            output_contract="natural_language_answer",
            tool_calls=calls,
            required_evidence=["sample_size"],
        ),
    )


def _run(
    registry: ToolRegistry,
    controller: SequenceController,
    *,
    policy: RuntimePolicy | None = None,
    clock: FakeClock | None = None,
) -> AgentRunState:
    runner = AgentGraphRunner(
        controller,  # type: ignore[arg-type]
        registry,
        runtime_policy=policy,
        clock=clock,
    )
    runner.answer_synthesizer = FixedAnswerSynthesizer()  # type: ignore[assignment]
    return asyncio.run(runner.run(AgentRunState(query="fixture", game="dota2")))


def test_missing_evidence_replan_reuses_success_and_completes() -> None:
    calls: list[str] = []
    controller = SequenceController(_decision(), _decision(recovered=True))

    state = _run(_registry(calls), controller)

    assert state.status == "ok"
    assert state.run_budget is not None
    assert state.run_budget.replans_used == 1
    assert state.run_budget.controller_calls_used == 2
    assert state.run_budget.tool_calls_used == 2
    assert calls == ["base", "sample"]
    assert [attempt.recovery_code for attempt in state.attempts] == [
        None,
        "missing_evidence",
    ]
    assert [call.reused for call in state.attempts[1].tool_calls] == [True, False]
    assert state.response["runtime"]["attempts"][1]["tool_call_statuses"][0][
        "reused"
    ]
    assert controller.calls[0]["recent_messages"] is None
    assert controller.calls[1]["recovery_feedback"].missing_evidence == [
        "sample_size"
    ]
    public = str(state.response)
    for private_name in (
        "recovery_feedback",
        "recovery_baseline_decision",
        "executed_call_fingerprints",
        "fingerprint",
    ):
        assert private_name not in public


def test_second_attempt_missing_evidence_is_replan_exhausted() -> None:
    calls: list[str] = []
    state = _run(
        _registry(calls, producer_emits=False),
        SequenceController(_decision(), _decision(recovered=True)),
    )

    assert state.status == "insufficient_evidence"
    assert state.response_type == "replan_exhausted"
    assert len(state.attempts) == 2
    assert state.attempts[1].recovery_code == "missing_evidence"


def test_missing_evidence_without_unused_producer_stays_single_attempt() -> None:
    state = _run(
        _registry([], include_producer=False),
        SequenceController(_decision()),
    )

    assert state.status == "insufficient_evidence"
    assert state.response_type == "insufficient_evidence"
    assert len(state.attempts) == 1
    assert state.run_budget.replans_used == 0


def test_recovery_stops_when_original_plan_has_no_append_capacity() -> None:
    calls: list[str] = []
    initial = _decision()
    initial.plan.constraints.max_tool_calls = 1
    controller = SequenceController(initial, _decision(recovered=True))

    state = _run(_registry(calls), controller)

    assert state.status == "insufficient_evidence"
    assert state.response_type == "replan_exhausted"
    assert len(state.attempts) == 1
    assert state.run_budget.replans_used == 0
    assert state.run_budget.controller_calls_used == 1
    assert calls == ["base"]


@pytest.mark.parametrize(
    "missing",
    [
        ["base:sample_size"],
        ["base: evidence_extractor_failed: ValueError: broken", "sample_size"],
    ],
)
def test_per_call_and_extractor_gaps_are_not_recoverable(missing: list[str]) -> None:
    decision = _decision()
    state = AgentRunState(
        query="fixture",
        game="dota2",
        decision=decision,
        plan=decision.plan,
        effective_required_evidence=["sample_size"],
        evidence_graph=EvidenceGraph(
            intent="fixture",
            required_evidence=["sample_size"],
            missing=missing,
            data_quality=EvidenceDataQuality(completeness=0),
        ),
    )

    assert recoverable_missing_evidence(state, _registry([])) is None


@pytest.mark.parametrize(
    "policy",
    [
        RuntimePolicy(max_controller_calls=1),
        RuntimePolicy(max_tool_calls_total=1),
    ],
)
def test_recoverable_gap_with_exhausted_budget_is_replan_exhausted(
    policy: RuntimePolicy,
) -> None:
    state = _run(_registry([]), SequenceController(_decision()), policy=policy)

    assert state.status == "insufficient_evidence"
    assert state.response_type == "replan_exhausted"
    assert len(state.attempts) == 1
    assert state.run_budget.replans_used == 0


def test_recoverable_gap_with_exhausted_replan_budget_is_replan_exhausted() -> None:
    clock = FakeClock(UTC_START)
    registry = _registry([])
    decision = _decision()
    state = AgentRunState(
        query="fixture",
        game="dota2",
        decision=decision,
        decision_kind="tool_plan",
        plan=decision.plan,
        global_required_evidence=["sample_size"],
        effective_required_evidence=["sample_size"],
        evidence_graph=EvidenceGraph(
            intent="fixture",
            required_evidence=["sample_size"],
            missing=["sample_size"],
            data_quality=EvidenceDataQuality(completeness=0),
        ),
        status="insufficient_evidence",
    )
    run_init_node(state, RuntimePolicy(), clock)
    state.run_budget.replans_used = 1
    attempt_finalize_node(state, clock)

    recovery_node(state, registry, clock)

    assert state.recovery_action == "terminal"
    assert state.response_type == "replan_exhausted"
    assert len(state.attempts) == 1


def test_recovery_requires_enough_tool_budget_for_complete_producer_cover() -> None:
    registry = ToolRegistry()
    for name, evidence_kinds in (
        ("debug.base_pair", ("kind_a", "kind_b")),
        ("debug.kind_a", ("kind_a",)),
        ("debug.kind_b", ("kind_b",)),
    ):
        registry.register(
            ToolDefinition(
                name=name,
                description="Synthetic producer cover.",
                input_model=ValueInput,
                handler=lambda args, context: {},
                source=ToolSource(name="UnitTest", kind="fixture"),
                evidence_extractor=_empty_evidence,
                evidence_kinds=evidence_kinds,
            )
        )
    decision = ToolPlanDecision(
        kind="tool_plan",
        plan=ExecutionPlan(
            intent="fixture",
            goal="Require two distinct unused producers.",
            output_contract="natural_language_answer",
            tool_calls=[ToolCall(id="base", tool="debug.base_pair")],
            required_evidence=["kind_a", "kind_b"],
        ),
    )
    state = AgentRunState(
        query="fixture",
        game="dota2",
        decision=decision,
        decision_kind="tool_plan",
        plan=decision.plan,
        global_required_evidence=["kind_a", "kind_b"],
        effective_required_evidence=["kind_a", "kind_b"],
        evidence_graph=EvidenceGraph(
            intent="fixture",
            required_evidence=["kind_a", "kind_b"],
            missing=["kind_a", "kind_b"],
            data_quality=EvidenceDataQuality(completeness=0),
        ),
        status="insufficient_evidence",
    )
    clock = FakeClock(UTC_START)
    run_init_node(state, RuntimePolicy(max_tool_calls_total=2), clock)
    state.run_budget.tool_calls_used = 1
    attempt_finalize_node(state, clock)

    recovery_node(state, registry, clock)

    assert state.recovery_action == "terminal"
    assert state.response_type == "replan_exhausted"
    assert state.run_budget.replans_used == 0


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("old_call", "exact prefix"),
        ("contract", "plan.output_contract"),
        ("constraints", "plan.constraints"),
        ("required", "required_evidence exactly"),
        ("coverage", "do not cover missing evidence"),
        ("missing_append", "append at least one"),
        ("reused_id", "call ids must be new"),
        ("reused_tool", "previously unused tools"),
        ("tool_budget", "exceed remaining run tool budget"),
    ],
)
def test_replan_validator_rejects_prefix_and_scope_changes(
    mutation: str,
    message: str,
) -> None:
    registry = _registry([])
    baseline = _decision()
    candidate = _decision(recovered=True)
    if mutation == "old_call":
        candidate.plan.tool_calls[0].args = {"value": 9}
    elif mutation == "contract":
        candidate.plan.output_contract = "other_contract"
    elif mutation == "constraints":
        candidate.plan.constraints.max_tool_calls = 5
    elif mutation == "required":
        candidate.plan.required_evidence.append("base")
    elif mutation == "coverage":
        candidate.plan.tool_calls[-1].tool = "debug.other"
    elif mutation == "missing_append":
        candidate.plan.tool_calls.pop()
    elif mutation == "reused_id":
        candidate.plan.tool_calls[-1].id = "base"
    elif mutation == "reused_tool":
        candidate.plan.tool_calls[-1].tool = "debug.base"

    errors = validate_replan_decision(
        candidate,
        baseline,
        RecoveryFeedback(
            missing_evidence=["sample_size"],
            remaining_tool_budget=3,
        ),
        registry,
        remaining_tool_budget=0 if mutation == "tool_budget" else 3,
    )

    assert any(message in error for error in errors)


def test_replan_validator_rejects_irrelevant_appended_tool() -> None:
    registry = _registry([])
    candidate = _decision(recovered=True)
    candidate.plan.tool_calls.append(
        ToolCall(id="other", tool="debug.other", args={"value": 3})
    )

    errors = validate_replan_decision(
        candidate,
        _decision(),
        RecoveryFeedback(
            missing_evidence=["sample_size"],
            remaining_tool_budget=3,
        ),
        registry,
        remaining_tool_budget=3,
    )

    assert "replan appended tools must produce missing evidence: debug.other" in errors


def test_tool_fingerprint_is_canonical_and_context_neutral() -> None:
    context = QueryContext()

    first = tool_call_fingerprint("debug.base", {"a": 1, "b": 2}, context)
    reordered = tool_call_fingerprint("debug.base", {"b": 2, "a": 1}, context)

    assert first == reordered
    assert first != tool_call_fingerprint("debug.base", {"a": 2, "b": 2}, context)


def test_duplicate_fingerprint_with_new_call_id_is_budget_error() -> None:
    calls: list[str] = []
    registry = _registry(calls)
    state = AgentRunState(
        query="fixture",
        game="dota2",
        plan=ExecutionPlan(
            intent="fixture",
            goal="Reject a duplicate call.",
            output_contract="natural_language_answer",
            tool_calls=[
                ToolCall(id="first", tool="debug.base", args={"value": 1}),
                ToolCall(id="renamed", tool="debug.base", args={"value": 1}),
            ],
        ),
    )
    clock = FakeClock(UTC_START)
    run_init_node(state, RuntimePolicy(), clock)
    asyncio.run(tool_executor_node(state, ToolExecutor(registry), clock))

    assert calls == ["base"]
    assert state.runtime_failure_code == "execution_budget_error"
    assert state.run_budget.tool_calls_used == 1


def test_failed_fingerprint_is_reused_without_retry() -> None:
    count = 0

    def fail(_args, _context):
        nonlocal count
        count += 1
        raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="debug.fail",
            description="Fail deterministically.",
            input_model=ValueInput,
            handler=fail,
        )
    )
    plan = ExecutionPlan(
        intent="fixture",
        goal="Do not retry failures.",
        output_contract="natural_language_answer",
        tool_calls=[ToolCall(id="failure", tool="debug.fail", args={"value": 1})],
    )
    clock = FakeClock(UTC_START)
    state = AgentRunState(query="fixture", game="dota2", plan=plan)
    run_init_node(state, RuntimePolicy(), clock)
    asyncio.run(tool_executor_node(state, ToolExecutor(registry), clock))
    next(iter(state.executed_call_fingerprints.values())).result.latency_ms = 37
    reset = reset_attempt_working_state(
        state,
        next_attempt_index=1,
        started_at=clock.now_utc(),
        started_monotonic=clock.monotonic(),
    )
    reset.plan = plan
    asyncio.run(tool_executor_node(reset, ToolExecutor(registry), clock))

    assert count == 1
    assert reset.run_budget.tool_calls_used == 1
    assert reset.tool_dispatch_records[0].stage == "cache_reuse"
    assert reset.tool_results[0].status == "error"
    assert reset.tool_results[0].latency_ms == 37


def test_shared_and_attempt_start_deadline_guards_close_the_run() -> None:
    clock = FakeClock(UTC_START)

    class SlowController(SequenceController):
        async def decide(self, query, game="dota2", history=None, **kwargs):
            clock.advance(1)
            return await super().decide(query, game, history, **kwargs)

    state = _run(
        _registry([]),
        SlowController(_decision()),
        policy=RuntimePolicy(max_elapsed_seconds=1),
        clock=clock,
    )
    assert state.status == "error"
    assert state.response_type == "execution_timeout"
    assert len(state.attempts) == 1
    assert state.response is not None

    reset_state = AgentRunState(query="fixture", game="dota2")
    clock = FakeClock(UTC_START)
    run_init_node(reset_state, RuntimePolicy(max_elapsed_seconds=1), clock)
    attempt_finalize_node(reset_state, clock)
    reset_state.recovery_action = "replan"
    reset_state.recovery_feedback = RecoveryFeedback(
        missing_evidence=["sample_size"],
        remaining_tool_budget=1,
    )
    reset_state.recovery_baseline_decision = _decision()
    clock.advance(1)

    attempt_reset_node(reset_state, clock)

    assert reset_state.recovery_action == "terminal"
    assert reset_state.runtime_failure_code == "execution_timeout"
    assert len(reset_state.attempts) == 1


@pytest.mark.parametrize(
    ("advance_seconds", "expected_code"),
    [(0, "execution_budget_error"), (1, "execution_timeout")],
)
def test_each_unreused_handler_checks_budget_and_deadline(
    advance_seconds: int,
    expected_code: str,
) -> None:
    clock = FakeClock(UTC_START)
    calls: list[str] = []
    registry = ToolRegistry()

    def first(_args, _context):
        calls.append("first")
        if advance_seconds:
            clock.advance(advance_seconds)
        return {"ok": True}

    registry.register(
        ToolDefinition(
            name="debug.first",
            description="First handler.",
            input_model=ValueInput,
            handler=first,
        )
    )
    registry.register(
        ToolDefinition(
            name="debug.second",
            description="Second handler.",
            input_model=ValueInput,
            handler=lambda args, context: calls.append("second") or {"ok": True},
        )
    )
    decision = ToolPlanDecision(
        kind="tool_plan",
        plan=ExecutionPlan(
            intent="fixture",
            goal="Check every handler gate.",
            output_contract="natural_language_answer",
            tool_calls=[
                ToolCall(id="first", tool="debug.first"),
                ToolCall(id="second", tool="debug.second"),
            ],
        ),
    )
    policy = RuntimePolicy(
        max_tool_calls_total=1 if not advance_seconds else 2,
        max_elapsed_seconds=1,
    )

    state = _run(
        registry,
        SequenceController(decision),
        policy=policy,
        clock=clock,
    )

    assert calls == ["first"]
    assert state.response_type == expected_code
    assert state.run_budget.tool_calls_used == 1
    assert len(state.attempts) == 1
