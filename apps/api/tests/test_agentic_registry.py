import asyncio

import pytest
from pydantic import BaseModel, Field

from app.agentic.models import ToolCall, ToolSource
from app.agentic.registry import ToolDefinition, ToolExecutor, ToolRegistry
from app.agentic.stratz_tools import build_default_tool_registry
from app.core.config import Settings


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


def test_default_registry_includes_agentic_data_tools() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )

    names = {definition.name for definition in registry.list()}

    assert {
        "resolve_hero",
        "stratz.hero_vs_hero_matchup",
        "stratz.lane_outcome",
        "opendota.resolve_team",
        "opendota.team_recent_matches",
        "opendota.team_players",
        "opendota.team_heroes",
        "opendota.hero_stats_by_role",
        "patch.get_records",
        "patch.hero_changes",
        "patch.item_changes",
    } <= names
