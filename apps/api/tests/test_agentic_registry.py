import asyncio

import pytest
from pydantic import BaseModel, Field

import app.agentic.tools.stratz_tools as stratz_tools
from app.agentic.evidence import EvidenceItem
from app.agentic.models import QueryContext, ToolCall, ToolResult, ToolSource
from app.agentic.planning.controller import AgentController
from app.agentic.tools import ToolDefinition, ToolExecutor, ToolRegistry
from app.agentic.tools.dota_catalog_tools import ResolveHeroInput
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings
from app.integrations.valve.catalog_repository import (
    CatalogSnapshotError,
    DotaCatalogRepository,
)


class EchoInput(BaseModel):
    value: int = Field(gt=0)


def _echo_definition(name: str = "debug.echo") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="Return the input value.",
        input_model=EchoInput,
        handler=lambda args, context: {"echo": args.value},
    )


def test_tool_registry_freeze_is_idempotent_and_blocks_registration() -> None:
    registry = ToolRegistry()
    registry.register(_echo_definition())

    registry.freeze()
    registry.freeze()

    with pytest.raises(RuntimeError, match="tool registry is frozen"):
        registry.register(_echo_definition("debug.late"))

    assert registry.get("debug.echo").name == "debug.echo"


def test_controller_freezes_the_registry_before_caching_its_prompt() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )
    controller = AgentController(registry, llm_enabled=False)

    with pytest.raises(RuntimeError, match="tool registry is frozen"):
        registry.register(_echo_definition("debug.late"))

    assert controller.prompt_versions["controller.system.sha256"]


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

    result, dispatch = asyncio.run(
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
    assert dispatch.handler_entered is True


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
    result, dispatch = asyncio.run(
        ToolExecutor(ToolRegistry()).execute(
            ToolCall(id="t1", tool="debug.missing", args={}),
            QueryContext(),
        )
    )

    assert result.status == "error"
    assert result.error
    assert "unknown tool" in result.error
    assert dispatch.error_code == "tool_not_registered"


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

    result, dispatch = asyncio.run(
        ToolExecutor(registry).execute(
            ToolCall(id="t1", tool="debug.echo", args={"value": 0}),
            QueryContext(),
        )
    )

    assert result.status == "error"
    assert result.error
    assert "ValidationError" in result.error
    assert dispatch.error_code == "input_validation_error"


def test_default_registry_matches_v32_frozen_tool_catalog() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )

    names = {definition.name for definition in registry.list()}

    assert names == {
        "resolve_hero",
        "stratz.pair_lane_outcome",
        "stratz.hero_matchup_ranking",
        "stratz.hero_synergy_ranking",
        "stratz.lane_meta_global",
        "stratz.hero_position_stats",
        "stratz.hero_daily_trends",
        "stratz.filter_heroes_by_position",
        "stratz.player_profile",
        "stratz.player_recent_matches",
        "stratz.player_hero_performance",
        "opendota.resolve_team",
        "opendota.team_recent_matches",
        "opendota.team_players",
        "opendota.team_heroes",
        "opendota.hero_stats_by_role",
        "patch.get_records",
        "patch.hero_changes",
        "patch.item_changes",
    }


def test_default_registry_uses_unique_catalog_resolve_hero() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )

    definitions = [
        definition for definition in registry.list() if definition.name == "resolve_hero"
    ]
    assert len(definitions) == 1
    definition = definitions[0]
    result = definition.handler(ResolveHeroInput(query="火女"), QueryContext())

    assert result["status"] == "resolved"
    assert result["method"] == "exact"
    assert result["hero"]["hero_id"] == 25
    assert result["hero"]["name"] == "npc_dota_hero_lina"
    assert result["snapshot"]["patch"] == "7.41e"
    assert definition.source is not None
    assert definition.source.kind == "official_snapshot"
    assert definition.source.status == "committed_snapshot"
    assert definition.input_model.__module__ == "app.agentic.tools.dota_catalog_tools"
    assert definition.evidence_extractor is not None
    assert definition.evidence_extractor.__module__ == "app.agentic.tools.dota_catalog_tools"
    assert definition.metadata["snapshot"] is True
    assert not hasattr(stratz_tools, "ResolveHeroInput")
    assert not hasattr(stratz_tools, "resolve_hero_evidence")
    assert not hasattr(stratz_tools, "_resolve_hero_handler")


def test_default_registry_keeps_resolve_hero_reference_contracts() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )

    pair_contract = registry.get("stratz.pair_lane_outcome").arg_contracts["hero_id"]
    reference = pair_contract.accepts_refs[0]
    assert reference.from_tool == "resolve_hero"
    assert reference.path == "data.hero.hero_id"
    assert reference.type == "int"
    open_dota_contract = registry.get("opendota.team_recent_matches").arg_contracts[
        "team_id"
    ]
    open_dota_reference = open_dota_contract.accepts_refs[0]
    assert open_dota_reference.from_tool == "opendota.resolve_team"
    assert open_dota_reference.path == "data.team.team_id"


def test_stratz_hero_name_index_uses_catalog_english_names_and_fails_fast(
    monkeypatch, tmp_path
) -> None:
    stratz_tools._hero_name_index.cache_clear()
    names = stratz_tools._hero_name_index()
    assert names[1] == "Anti-Mage"
    assert names[25] == "Lina"
    assert names[86] == "Rubick"

    monkeypatch.setattr(
        stratz_tools,
        "load_default_catalog_repository",
        lambda: DotaCatalogRepository(tmp_path),
    )
    stratz_tools._hero_name_index.cache_clear()
    try:
        with pytest.raises(CatalogSnapshotError, match="catalog file missing"):
            stratz_tools._hero_name_index()
    finally:
        stratz_tools._hero_name_index.cache_clear()


def test_default_registry_declares_primary_mandatory_evidence() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )
    expected = {
        "resolve_hero": ("hero_identity",),
        "stratz.pair_lane_outcome": ("pair_lane_winrate",),
        "stratz.hero_matchup_ranking": ("matchup_ranking_row",),
        "stratz.hero_synergy_ranking": ("hero_synergy_ranking_row",),
        "stratz.lane_meta_global": ("lane_meta_row",),
        "stratz.hero_position_stats": ("position_stat",),
        "stratz.hero_daily_trends": ("hero_daily_trend",),
        "stratz.filter_heroes_by_position": ("role_filtered_candidate_row",),
        "stratz.player_profile": ("player_identity",),
        "stratz.player_recent_matches": ("player_recent_summary",),
        "stratz.player_hero_performance": ("player_hero_performance",),
        "opendota.resolve_team": ("team_identity",),
        "opendota.team_recent_matches": ("recent_matches",),
        "opendota.team_players": ("current_players",),
        "opendota.team_heroes": ("team_hero_usage",),
        "opendota.hero_stats_by_role": ("hero_stats",),
        "patch.get_records": ("patch_records",),
        "patch.hero_changes": ("hero_patch_changes",),
        "patch.item_changes": ("item_patch_changes",),
    }

    assert {
        name: registry.get(name).mandatory_evidence for name in expected
    } == expected
    assert all("sample_size" not in kinds for kinds in expected.values())
