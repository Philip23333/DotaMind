import asyncio

import pytest
from pydantic import BaseModel, Field

from app.agentic.models import ExecutionConstraints, ExecutionPlan, ToolCall, ToolSource
from app.agentic.registry import ToolDefinition, ToolExecutor, ToolRegistry


class EchoInput(BaseModel):
    value: int = Field(gt=0)


def test_tool_registry_executes_registered_tool() -> None:
    async def handler(args: EchoInput) -> dict:
        return {"echo": args.value}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="debug.echo",
            description="Return the input value.",
            input_model=EchoInput,
            handler=handler,
            source=ToolSource(name="UnitTest", kind="fixture"),
            metadata={"domain": "test"},
        )
    )

    result = asyncio.run(
        ToolExecutor(registry).execute(
            ToolCall(id="t1", tool="debug.echo", args={"value": 7})
        )
    )

    assert result.status == "ok"
    assert result.tool_call_id == "t1"
    assert result.data == {"echo": 7}
    assert result.source
    assert result.source.name == "UnitTest"
    assert result.metadata == {"domain": "test"}
    assert result.latency_ms >= 0


def test_tool_registry_rejects_duplicate_tool_names() -> None:
    registry = ToolRegistry()
    definition = ToolDefinition(
        name="debug.echo",
        description="Return the input value.",
        input_model=EchoInput,
        handler=lambda args: {"echo": args.value},
    )

    registry.register(definition)

    with pytest.raises(ValueError, match="tool already registered"):
        registry.register(definition)


def test_tool_executor_returns_error_for_unknown_tool() -> None:
    result = asyncio.run(
        ToolExecutor(ToolRegistry()).execute(
            ToolCall(id="t1", tool="debug.missing", args={})
        )
    )

    assert result.status == "error"
    assert result.error
    assert "unknown tool" in result.error


def test_tool_executor_returns_error_for_invalid_args() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="debug.echo",
            description="Return the input value.",
            input_model=EchoInput,
            handler=lambda args: {"echo": args.value},
        )
    )

    result = asyncio.run(
        ToolExecutor(registry).execute(
            ToolCall(id="t1", tool="debug.echo", args={"value": 0})
        )
    )

    assert result.status == "error"
    assert result.error
    assert "ValidationError" in result.error


def test_tool_executor_executes_plan_calls() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="debug.echo",
            description="Return the input value.",
            input_model=EchoInput,
            handler=lambda args: {"echo": args.value},
        )
    )
    plan = ExecutionPlan(
        intent="debug",
        goal="Run debug tools.",
        output_contract="tool_results",
        tool_calls=[
            ToolCall(id="t1", tool="debug.echo", args={"value": 1}),
            ToolCall(id="t2", tool="debug.echo", args={"value": 2}),
        ],
        required_evidence=["debug_output"],
    )

    results = asyncio.run(ToolExecutor(registry).execute_plan(plan))

    assert [result.status for result in results] == ["ok", "ok"]
    assert [result.data for result in results] == [{"echo": 1}, {"echo": 2}]


def test_tool_executor_rejects_plan_over_tool_call_limit() -> None:
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

    results = asyncio.run(ToolExecutor(ToolRegistry()).execute_plan(plan))

    assert len(results) == 1
    assert results[0].status == "error"
    assert results[0].tool_call_id == "plan"
    assert "max_tool_calls" in (results[0].error or "")
