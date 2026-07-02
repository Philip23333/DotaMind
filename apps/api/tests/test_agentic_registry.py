import asyncio

import pytest
from pydantic import BaseModel, Field

from app.agentic.evidence import EvidenceItem
from app.agentic.models import QueryContext, ToolCall, ToolResult, ToolSource
from app.agentic.tools import ToolDefinition, ToolExecutor, ToolRegistry
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings


class EchoInput(BaseModel):
    value: int = Field(gt=0)


def test_tool_registry_executes_registered_tool() -> None:
    async def handler(args: EchoInput, context: QueryContext) -> dict:
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
            ToolCall(id="t1", tool="debug.echo", args={"value": 7}),
            QueryContext(),
        )
    )

    assert result.status == "ok"
    assert result.tool_call_id == "t1"
    assert result.data == {"echo": 7}
    assert result.source
    assert result.source.name == "UnitTest"
    assert result.metadata == {"domain": "test"}
    assert result.latency_ms >= 0


def test_tool_registry_accepts_optional_evidence_extractor() -> None:
    def extractor(result: ToolResult) -> list[EvidenceItem]:
        return [
            EvidenceItem(
                id=f"{result.tool_call_id}:echo",
                kind="debug_evidence",
                subject="debug",
                value={"ok": True},
                tool_call_id=result.tool_call_id,
                tool=result.tool,
            )
        ]

    definition = ToolDefinition(
        name="debug.echo",
        description="Return the input value.",
        input_model=EchoInput,
        handler=lambda args, context: {"echo": args.value},
        evidence_extractor=extractor,
        evidence_kinds=("debug_evidence",),
    )

    registry = ToolRegistry()
    registry.register(definition)

    registered = registry.get("debug.echo")
    assert registered.evidence_extractor is extractor
    assert registered.evidence_kinds == ("debug_evidence",)


def test_tool_registry_accepts_utility_tool_without_evidence() -> None:
    definition = ToolDefinition(
        name="debug.utility",
        description="Utility tool.",
        input_model=EchoInput,
        handler=lambda args, context: {"echo": args.value},
    )

    registry = ToolRegistry()
    registry.register(definition)

    registered = registry.get("debug.utility")
    assert registered.evidence_extractor is None
    assert registered.evidence_kinds == ()


def test_tool_registry_rejects_duplicate_tool_names() -> None:
    registry = ToolRegistry()
    definition = ToolDefinition(
        name="debug.echo",
        description="Return the input value.",
        input_model=EchoInput,
        handler=lambda args, context: {"echo": args.value},
    )

    registry.register(definition)

    with pytest.raises(ValueError, match="tool already registered"):
        registry.register(definition)


def test_tool_executor_returns_error_for_unknown_tool() -> None:
    result = asyncio.run(
        ToolExecutor(ToolRegistry()).execute(
            ToolCall(id="t1", tool="debug.missing", args={}),
            QueryContext(),
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
            handler=lambda args, context: {"echo": args.value},
        )
    )

    result = asyncio.run(
        ToolExecutor(registry).execute(
            ToolCall(id="t1", tool="debug.echo", args={"value": 0}),
            QueryContext(),
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
