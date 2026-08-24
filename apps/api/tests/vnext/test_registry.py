from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel, ConfigDict

from app.vnext.llm.protocol import ModelTool, ToolCall
from app.vnext.tools import ToolDefinition, ToolRegistry


class EchoInput(BaseModel):
    value: int


class EchoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


def _echo_registry(handler=None, *, parallel_safe: bool = False) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="Return the supplied value.",
            input_model=EchoInput,
            output_model=EchoOutput,
            handler=handler or (lambda args: EchoOutput(value=args.value)),
            parallel_safe=parallel_safe,
        )
    )
    return registry


def _call(value: object = 1, *, call_id: str = "call-1") -> ToolCall:
    return ToolCall(id=call_id, name="echo", arguments={"value": value})


def test_register_duplicate_names_fail_and_schemas_are_provider_neutral() -> None:
    registry = _echo_registry()
    with pytest.raises(ValueError, match="already registered"):
        registry.register(
            ToolDefinition(
                name="echo",
                description="duplicate",
                input_model=EchoInput,
                output_model=EchoOutput,
                handler=lambda args: EchoOutput(value=args.value),
            )
        )

    schema = registry.schemas()[0]
    assert isinstance(schema, ModelTool)
    assert schema.name == "echo"
    assert schema.description == "Return the supplied value."
    assert schema.input_schema["properties"]["value"]["type"] == "integer"
    assert "type" not in schema.model_dump()
    assert "function" not in schema.model_dump()


def test_input_and_output_models_are_validated() -> None:
    registry = _echo_registry()
    invalid_input = asyncio.run(registry.execute(_call("not-an-int")))
    assert invalid_input.status == "error"
    assert invalid_input.error is not None
    assert invalid_input.error.code == "invalid_arguments"

    bad_output = _echo_registry(handler=lambda args: {"wrong": args.value})
    invalid_output = asyncio.run(bad_output.execute(_call()))
    assert invalid_output.status == "error"
    assert invalid_output.error is not None
    assert invalid_output.error.code == "invalid_tool_output"


def test_unknown_tool_and_handler_exception_are_explicit_errors() -> None:
    secret = "provider token: sk-live-secret"
    registry = _echo_registry(
        handler=lambda args: (_ for _ in ()).throw(RuntimeError(secret))
    )
    unknown = asyncio.run(registry.execute(ToolCall(id="missing-1", name="missing", arguments={})))
    failed = asyncio.run(registry.execute(_call()))

    assert unknown.tool_call_id == "missing-1"
    assert unknown.error is not None and unknown.error.code == "unknown_tool"
    assert failed.error is not None and failed.error.code == "tool_execution_error"
    assert failed.error.details == {}
    serialized = failed.model_dump_json()
    assert secret not in serialized
    assert "RuntimeError" not in serialized


def test_tool_timeout_is_a_tool_result_and_not_a_success() -> None:
    async def slow(args: EchoInput) -> EchoOutput:
        await asyncio.sleep(0.03)
        return EchoOutput(value=args.value)

    registry = _echo_registry(handler=slow)
    result = asyncio.run(registry.execute(_call(), timeout=0.001))
    assert result.status == "error"
    assert result.error is not None and result.error.code == "tool_timeout"


def test_parallel_safe_calls_can_run_concurrently_and_keep_input_order() -> None:
    state = {"active": 0, "maximum": 0}

    async def concurrent(args: EchoInput) -> EchoOutput:
        state["active"] += 1
        state["maximum"] = max(state["maximum"], state["active"])
        await asyncio.sleep(0.02)
        state["active"] -= 1
        return EchoOutput(value=args.value)

    registry = _echo_registry(handler=concurrent, parallel_safe=True)
    results = asyncio.run(
        registry.execute_many([_call(1, call_id="a"), _call(2, call_id="b")])
    )
    assert state["maximum"] == 2
    assert [result.tool_call_id for result in results] == ["a", "b"]
    assert [result.content for result in results] == [{"value": 1}, {"value": 2}]
