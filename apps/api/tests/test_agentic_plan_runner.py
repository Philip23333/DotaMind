import asyncio

from pydantic import BaseModel, Field

from app.agentic.models import ExecutionConstraints, ExecutionPlan, ToolCall
from app.agentic.registry import ToolDefinition, ToolExecutor, ToolRegistry
from app.agentic.runner import PlanRunner


class EchoInput(BaseModel):
    value: int = Field(gt=0)


class HeroLookupInput(BaseModel):
    query: str


class MatchupInput(BaseModel):
    hero_id: int
    take: int = 3


def test_plan_runner_executes_tools_and_resolves_references() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="debug.resolve_hero",
            description="Resolve a fake hero.",
            input_model=HeroLookupInput,
            handler=lambda args: {"hero": {"hero_id": 25, "name": args.query}},
        )
    )
    registry.register(
        ToolDefinition(
            name="debug.matchups",
            description="Fetch fake matchup rows.",
            input_model=MatchupInput,
            handler=lambda args: {"hero_id": args.hero_id, "take": args.take},
        )
    )
    plan = ExecutionPlan(
        intent="debug",
        goal="Resolve a hero then fetch matchups.",
        output_contract="tool_results",
        tool_calls=[
            ToolCall(
                id="resolve_target",
                tool="debug.resolve_hero",
                args={"query": "Lina"},
            ),
            ToolCall(
                id="get_matchups",
                tool="debug.matchups",
                args={
                    "hero_id": "$resolve_target.data.hero.hero_id",
                    "take": 5,
                },
            ),
        ],
    )

    result = asyncio.run(PlanRunner(ToolExecutor(registry)).run(plan))

    assert result.status == "ok"
    assert result.errors == []
    assert [item.tool_call_id for item in result.tool_results] == [
        "resolve_target",
        "get_matchups",
    ]
    assert result.tool_results[1].data == {"hero_id": 25, "take": 5}
    assert result.evidence_graph
    assert result.evidence_graph.intent == "debug"


def test_plan_runner_returns_error_for_missing_reference_path() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="debug.resolve_hero",
            description="Resolve a fake hero.",
            input_model=HeroLookupInput,
            handler=lambda args: {"hero": {"hero_id": 25}},
        )
    )
    registry.register(
        ToolDefinition(
            name="debug.matchups",
            description="Fetch fake matchup rows.",
            input_model=MatchupInput,
            handler=lambda args: {"hero_id": args.hero_id},
        )
    )
    plan = ExecutionPlan(
        intent="debug",
        goal="Use an invalid reference path.",
        output_contract="tool_results",
        tool_calls=[
            ToolCall(
                id="resolve_target",
                tool="debug.resolve_hero",
                args={"query": "Lina"},
            ),
            ToolCall(
                id="get_matchups",
                tool="debug.matchups",
                args={"hero_id": "$resolve_target.data.missing.hero_id"},
            ),
        ],
    )

    result = asyncio.run(PlanRunner(ToolExecutor(registry)).run(plan))

    assert result.status == "error"
    assert len(result.tool_results) == 1
    assert "reference path not found" in result.errors[0]


def test_plan_runner_does_not_execute_tool_with_failed_dependency() -> None:
    calls = []
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="debug.fail",
            description="Always fail.",
            input_model=HeroLookupInput,
            handler=lambda _args: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    )
    registry.register(
        ToolDefinition(
            name="debug.matchups",
            description="Fetch fake matchup rows.",
            input_model=MatchupInput,
            handler=lambda args: calls.append(args.hero_id),
        )
    )
    plan = ExecutionPlan(
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
    )

    result = asyncio.run(PlanRunner(ToolExecutor(registry)).run(plan))

    assert result.status == "error"
    assert calls == []
    assert len(result.tool_results) == 1
    assert "reference target failed" in result.errors[-1]


def test_plan_runner_rejects_plan_over_tool_call_limit() -> None:
    plan = ExecutionPlan(
        intent="debug",
        goal="Run too many tools.",
        output_contract="tool_results",
        tool_calls=[
            ToolCall(id="t1", tool="debug.echo", args={}),
            ToolCall(id="t2", tool="debug.echo", args={}),
        ],
        constraints=ExecutionConstraints(max_tool_calls=1),
    )

    result = asyncio.run(PlanRunner(ToolExecutor(ToolRegistry())).run(plan))

    assert result.status == "error"
    assert result.tool_results == []
    assert "max_tool_calls" in result.errors[0]
    assert result.evidence_graph
    assert result.evidence_graph.tool_results == []


def test_plan_runner_rejects_duplicate_tool_call_ids() -> None:
    plan = ExecutionPlan(
        intent="debug",
        goal="Reject duplicate IDs.",
        output_contract="tool_results",
        tool_calls=[
            ToolCall(id="t1", tool="debug.echo", args={}),
            ToolCall(id="t1", tool="debug.echo", args={}),
        ],
    )

    result = asyncio.run(PlanRunner(ToolExecutor(ToolRegistry())).run(plan))

    assert result.status == "error"
    assert "duplicate tool call id" in result.errors[0]
