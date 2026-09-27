from __future__ import annotations

import asyncio
from typing import Any

import pytest
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel

from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry


class _Output(BaseModel):
    accepted: bool


def _definition(schema: dict[str, Any], calls: list[dict[str, Any]]) -> ToolDefinition:
    async def invoke(arguments: dict[str, Any]) -> dict[str, bool]:
        calls.append(arguments)
        return {"accepted": True}

    return ToolDefinition(
        name="remote.search",
        description="Test remote schema passthrough.",
        input_model=None,
        input_schema=schema,
        output_model=_Output,
        handler=invoke,
    )


def test_json_schema_is_passed_through_and_validates_nested_arguments() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 3},
            "filters": {
                "type": "object",
                "properties": {"topic": {"enum": ["general", "news"]}},
                "required": ["topic"],
                "additionalProperties": False,
            },
        },
        "required": ["query", "filters"],
        "additionalProperties": False,
    }
    calls: list[dict[str, Any]] = []
    registry = ToolRegistry()
    registry.register(_definition(schema, calls))

    assert registry.schemas()[0].input_schema == schema

    accepted = asyncio.run(
        registry.execute(
            ToolCall(
                id="valid",
                name="remote.search",
                arguments={"query": "TI 2026", "filters": {"topic": "news"}},
            )
        )
    )
    rejected = asyncio.run(
        registry.execute(
            ToolCall(
                id="invalid",
                name="remote.search",
                arguments={
                    "query": "x",
                    "filters": {"topic": "private-sensitive-value"},
                },
            )
        )
    )

    assert accepted.status == "ok"
    assert accepted.content == {"accepted": True}
    assert calls == [{"query": "TI 2026", "filters": {"topic": "news"}}]
    assert rejected.status == "error"
    assert rejected.error is not None
    assert rejected.error.code == "invalid_arguments"
    assert "private-sensitive-value" not in str(rejected.error.model_dump())


def test_invalid_or_remote_reference_schemas_are_rejected_at_registration() -> None:
    calls: list[dict[str, Any]] = []

    with pytest.raises(ValueError, match="must not contain remote references"):
        _definition(
            {
                "type": "object",
                "properties": {"query": {"$ref": "https://example.test/schema.json"}},
            },
            calls,
        )

    with pytest.raises(SchemaError):
        _definition(
            {"type": "object", "properties": {"query": {"type": "not-a-json-schema-type"}}},
            calls,
        )


def test_json_schema_rejects_non_object_tool_arguments() -> None:
    calls: list[dict[str, Any]] = []
    with pytest.raises(ValueError, match="root must describe an object"):
        _definition({"type": "string"}, calls)
