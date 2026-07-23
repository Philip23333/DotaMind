import asyncio

from pydantic import BaseModel

from app.agentic.answer import AnswerSynthesisResult
from app.agentic.critic import AgenticCriticReview
from app.agentic.evidence import EvidenceDataQuality, EvidenceGraph
from app.agentic.models import ExecutionConstraints, ExecutionPlan, ToolCall, ToolResult
from app.agentic.nodes import (
    attempt_finalize_node,
    evidence_node,
    response_node,
    run_finalize_node,
    run_init_node,
    tool_executor_node,
    validate_plan_node,
)
from app.agentic.runtime.clock import SystemClock
from app.agentic.runtime.summaries import resolve_terminal_outcome
from app.agentic.state import AgentRunState
from app.agentic.tools import (
    AcceptedRef,
    ArgContract,
    OutputPathContract,
    ToolDefinition,
    ToolExecutor,
    ToolRegistry,
)
from app.core.config import RuntimePolicy


def _finalize_response(state: AgentRunState) -> AgentRunState:
    clock = SystemClock()
    run_init_node(state, RuntimePolicy(), clock)
    attempt_finalize_node(state, clock)
    run_finalize_node(state, clock)
    return response_node(state)


def _execute_tools(state: AgentRunState, registry: ToolRegistry) -> AgentRunState:
    clock = SystemClock()
    run_init_node(state, RuntimePolicy(), clock)
    return asyncio.run(tool_executor_node(state, ToolExecutor(registry), clock))


class HeroLookupInput(BaseModel):
    query: str


class MatchupInput(BaseModel):
    hero_id: int
    take: int = 3


def test_validate_plan_rejects_too_many_tool_calls() -> None:
    state = AgentRunState(
        query="debug",
        game="dota2",
        plan=ExecutionPlan(
            intent="debug",
            goal="Run too many tools.",
            output_contract="tool_results",
            tool_calls=[
                ToolCall(id="t1", tool="debug.matchups", args={"hero_id": 1}),
                ToolCall(id="t2", tool="debug.matchups", args={"hero_id": 1}),
            ],
            constraints=ExecutionConstraints(max_tool_calls=1),
        ),
    )

    validate_plan_node(state, _registry())

    assert state.status == "error"
    assert "max_tool_calls" in state.errors[0]


def test_validate_plan_rejects_duplicate_tool_call_ids() -> None:
    state = AgentRunState(
        query="debug",
        game="dota2",
        plan=ExecutionPlan(
            intent="debug",
            goal="Reject duplicate IDs.",
            output_contract="tool_results",
            tool_calls=[
                ToolCall(id="t1", tool="debug.matchups", args={"hero_id": 1}),
                ToolCall(id="t1", tool="debug.matchups", args={"hero_id": 1}),
            ],
        ),
    )

    validate_plan_node(state, _registry())

    assert state.status == "error"
    assert "duplicate tool call id" in state.errors[0]


def test_tool_executor_node_executes_tools_and_resolves_references() -> None:
    state = AgentRunState(query="debug", game="dota2", plan=_debug_plan())

    result = _execute_tools(state, _registry())

    assert result.status == "ok"
    assert [item.tool_call_id for item in result.tool_results] == [
        "resolve_target",
        "get_matchups",
    ]
    assert result.tool_results[1].data == {"hero_id": 25, "take": 5}


def test_tool_executor_node_returns_error_for_missing_reference_path() -> None:
    plan = _debug_plan()
    plan.tool_calls[1].args = {"hero_id": "$resolve_target.data.missing.hero_id"}
    state = AgentRunState(query="debug", game="dota2", plan=plan)

    result = _execute_tools(state, _registry())

    assert result.status == "error"
    assert len(result.tool_results) == 2
    assert result.tool_results[1].status == "error"
    assert result.tool_results[1].metadata == {}
    assert result.tool_dispatch_records[1].stage == "reference_resolution"
    assert result.tool_dispatch_records[1].error_code == "reference_resolution_error"
    assert "reference path not found" in result.errors[0]

    outcome = resolve_terminal_outcome(result)
    assert outcome.response_type == "tool_error"
    assert outcome.stable_reason == "tool execution failed"


def test_tool_executor_node_skips_failed_dependency() -> None:
    calls = []
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="debug.fail",
            description="Always fail.",
            input_model=HeroLookupInput,
            handler=lambda _args, context: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    )
    registry.register(
        ToolDefinition(
            name="debug.matchups",
            description="Fetch fake matchup rows.",
            input_model=MatchupInput,
            handler=lambda args, context: calls.append(args.hero_id),
        )
    )
    state = AgentRunState(
        query="debug",
        game="dota2",
        plan=ExecutionPlan(
            intent="debug",
            goal="Do not run dependent tools.",
            output_contract="tool_results",
            tool_calls=[
                ToolCall(id="resolve_target", tool="debug.fail", args={"query": "Lina"}),
                ToolCall(
                    id="get_matchups",
                    tool="debug.matchups",
                    args={"hero_id": "$resolve_target.data.hero.hero_id"},
                ),
            ],
        ),
    )

    result = _execute_tools(state, registry)

    assert result.status == "error"
    assert calls == []
    assert len(result.tool_results) == 2
    assert result.tool_results[1].metadata == {}
    assert result.tool_dispatch_records[1].stage == "reference_resolution"
    assert "reference target failed" in result.errors[-1]


def test_evidence_node_builds_graph_from_tool_results() -> None:
    state = AgentRunState(query="debug", game="dota2", plan=_debug_plan())
    state = _execute_tools(state, _registry())

    evidence_node(state, _registry())

    assert state.evidence_graph
    assert state.evidence_graph.intent == "debug"
    assert len(state.evidence_graph.tool_results) == 2


def test_response_node_writes_response() -> None:
    state = AgentRunState(query="debug", game="dota2", status="ok", reason="done")

    _finalize_response(state)

    assert state.response
    assert state.response["status"] == "ok"
    assert state.response["response_type"] == "raw_tool_results"


def test_response_node_maps_insufficient_evidence() -> None:
    state = AgentRunState(query="debug", game="dota2", status="ok", reason="done")
    state.answer = AnswerSynthesisResult(
        answer_type="role_meta_report",
        status="insufficient_evidence",
        summary="missing hero_stats",
        confidence=0,
    )

    outcome = resolve_terminal_outcome(state)

    assert outcome.public_status == "insufficient_evidence"
    assert outcome.response_type == "insufficient_evidence"


def test_response_node_maps_answer_error() -> None:
    state = AgentRunState(query="debug", game="dota2", status="ok", reason="done")
    state.answer = AnswerSynthesisResult(
        answer_type="natural_language_answer",
        status="error",
        summary="LLM failed",
        confidence=0,
    )

    outcome = resolve_terminal_outcome(state)

    assert outcome.response_type == "answer_error"
    assert outcome.stable_reason == "answer generation failed"


def test_response_node_maps_unclassified_runtime_error_to_execution_error() -> None:
    state = AgentRunState(
        query="debug",
        game="dota2",
        status="error",
        reason="decision accepted",
        errors=["unexpected runtime failure"],
    )

    outcome = resolve_terminal_outcome(state)

    assert outcome.response_type == "execution_error"
    assert outcome.stable_reason == "execution failed"


def test_response_node_prioritizes_tool_error_over_missing_evidence() -> None:
    failed_tool = ToolResult(
        tool_call_id="upstream",
        tool="debug.failure",
        status="error",
        latency_ms=1,
        error="timeout",
    )
    state = AgentRunState(
        query="debug",
        game="dota2",
        status="error",
        tool_results=[failed_tool],
        evidence_graph=EvidenceGraph(
            intent="debug",
            required_evidence=["main_result"],
            tool_results=[failed_tool],
            missing=["upstream: tool_failed", "main_result"],
            data_quality=EvidenceDataQuality(completeness=0),
        ),
    )

    outcome = resolve_terminal_outcome(state)

    assert outcome.public_status == "error"
    assert outcome.response_type == "tool_error"


def test_response_node_prioritizes_answer_error_over_critic_failure() -> None:
    state = AgentRunState(query="debug", game="dota2", status="error")
    state.answer = AnswerSynthesisResult(
        answer_type="natural_language_answer",
        status="error",
        summary="LLM failed",
        confidence=0,
    )
    state.review = AgenticCriticReview(
        passed=False,
        severity="failed",
        reasons=["quality failure"],
    )

    outcome = resolve_terminal_outcome(state)

    assert outcome.public_status == "error"
    assert outcome.response_type == "answer_error"


def test_response_node_maps_structured_report() -> None:
    state = AgentRunState(query="debug", game="dota2", status="ok", reason="done")
    state.answer = AnswerSynthesisResult(
        answer_type="role_meta_report",
        status="ok",
        summary="done",
        confidence=1,
    )

    _finalize_response(state)

    assert state.response["response_type"] == "role_meta_report"


def _debug_plan() -> ExecutionPlan:
    return ExecutionPlan(
        intent="debug",
        goal="Resolve a hero then fetch matchups.",
        output_contract="tool_results",
        tool_calls=[
            ToolCall(id="resolve_target", tool="debug.resolve_hero", args={"query": "Lina"}),
            ToolCall(
                id="get_matchups",
                tool="debug.matchups",
                args={"hero_id": "$resolve_target.data.hero.hero_id", "take": 5},
            ),
        ],
    )


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="debug.resolve_hero",
            description="Resolve a fake hero.",
            input_model=HeroLookupInput,
            handler=lambda args, context: {"hero": {"hero_id": 25, "name": args.query}},
            output_paths={
                "hero_id": OutputPathContract(
                    path="data.hero.hero_id",
                    type="int",
                )
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="debug.matchups",
            description="Fetch fake matchup rows.",
            input_model=MatchupInput,
            handler=lambda args, context: {"hero_id": args.hero_id, "take": args.take},
            arg_contracts={
                "hero_id": ArgContract(
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="debug.resolve_hero",
                            path="data.hero.hero_id",
                            type="int",
                        ),
                    )
                )
            },
        )
    )
    return registry
