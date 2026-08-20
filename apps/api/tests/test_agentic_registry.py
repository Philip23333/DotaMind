import asyncio

import pytest
from pydantic import BaseModel, Field

import app.agentic.tools.stratz_tools as stratz_tools
from app.agentic.evidence import EvidenceItem
from app.agentic.models import ExecutionPlan, QueryContext, ToolCall, ToolResult, ToolSource
from app.agentic.planning.contracts import validate_plan_against_catalog
from app.agentic.planning.controller import AgentController
from app.agentic.tools import ToolDefinition, ToolExecutor, ToolRegistry
from app.agentic.tools.dota_catalog_tools import (
    HeroAbilitiesInput,
    HeroAttributesInput,
    HeroTalentTreeInput,
    ItemInfoInput,
    ResolveHeroInput,
    ResolveItemInput,
)
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings
from app.integrations.valve.catalog_repository import (
    CatalogLookupError,
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
        "dota.hero_attributes",
        "dota.hero_abilities",
        "dota.hero_talent_tree",
        "resolve_item",
        "dota.item_info",
        "stratz.pair_lane_outcome",
        "stratz.hero_matchup_ranking",
        "stratz.hero_synergy_ranking",
        "stratz.lane_meta_global",
        "stratz.hero_position_stats",
        "stratz.hero_daily_trends",
        "stratz.filter_ranked_heroes_by_position",
        "stratz.player_profile",
        "stratz.player_recent_matches",
        "stratz.player_hero_performance",
        "opendota.resolve_team",
        "opendota.team_recent_matches",
        "opendota.team_players",
        "opendota.team_heroes",
        "opendota.hero_stats_by_role",
        "pandascore.resolve_competition",
        "pandascore.list_matches",
        "pandascore.resolve_match_games",
        "dota.resolve_valve_matches",
        "opendota.match_details",
        "patch.get_records",
        "patch.hero_changes",
        "patch.item_changes",
        "conversation.history_lookup",
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


def test_hero_attributes_contract_handler_and_evidence_use_official_snapshot() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )
    definition = registry.get("dota.hero_attributes")
    result = definition.handler(HeroAttributesInput(hero_id=25), QueryContext())
    lina = DotaCatalogRepository().get_hero(25)

    assert definition.source is not None
    assert definition.source.kind == "official_snapshot"
    assert definition.source.status == "committed_snapshot"
    assert definition.mandatory_evidence == ("hero_attributes",)
    assert definition.arg_contracts["hero_id"].requires_reference is True
    accepted = definition.arg_contracts["hero_id"].accepts_refs
    assert [(item.from_tool, item.path, item.type) for item in accepted] == [
        ("resolve_hero", "data.hero.hero_id", "int")
    ]
    assert {item.path for item in definition.output_paths.values()} == {
        "data.hero",
        "data.attributes",
        "data.combat",
    }
    assert result["hero"] == {
        "hero_id": 25,
        "name": lina.internal_name,
        "name_en": lina.name_en,
        "name_zh": lina.name_zh,
        "aliases": lina.aliases,
    }
    assert result["attributes"]["strength_base"] == lina.strength_base
    assert result["attributes"]["agility_gain"] == lina.agility_gain
    assert result["combat"]["damage_min"] == lina.damage_min
    assert result["combat"]["movement_speed"] == lina.movement_speed
    assert result["snapshot"]["patch"] == "7.41e"
    assert "snapshot_dir" not in result["snapshot"]

    tool_result = ToolResult(
        tool_call_id="attributes",
        tool="dota.hero_attributes",
        status="ok",
        data=result,
        source=definition.source,
        latency_ms=0,
    )
    assert definition.evidence_extractor is not None
    evidence = definition.evidence_extractor(tool_result)
    assert len(evidence) == 1
    assert evidence[0].id == "attributes:hero_attributes:25"
    assert evidence[0].kind == "hero_attributes"
    assert evidence[0].tool_call_id == "attributes"
    assert evidence[0].source == definition.source
    assert evidence[0].value["hero"]["hero_id"] == 25
    assert evidence[0].value["attributes"] == result["attributes"]
    assert evidence[0].value["combat"] == result["combat"]
    assert evidence[0].value["snapshot"] == result["snapshot"]


def test_hero_attributes_requires_plan_local_resolve_reference() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )
    literal_plan = ExecutionPlan(
        intent="hero_attributes",
        goal="Show Lina attributes.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="attributes", tool="dota.hero_attributes", args={"hero_id": 25})
        ],
        required_evidence=["hero_attributes"],
    )
    errors = validate_plan_against_catalog(literal_plan, registry)
    assert (
        "dota.hero_attributes.hero_id must reference a previous current-plan tool result"
        in errors
    )

    referenced_plan = ExecutionPlan(
        intent="hero_attributes",
        goal="Show Lina attributes.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="resolve", tool="resolve_hero", args={"query": "莉娜"}),
            ToolCall(
                id="attributes",
                tool="dota.hero_attributes",
                args={"hero_id": "$resolve.data.hero.hero_id"},
            ),
        ],
        required_evidence=["hero_identity", "hero_attributes"],
    )
    assert validate_plan_against_catalog(referenced_plan, registry) == []


def test_hero_attributes_unknown_id_exposes_stable_lookup_and_tool_errors() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )
    definition = registry.get("dota.hero_attributes")

    with pytest.raises(CatalogLookupError, match="hero not found: 999999"):
        definition.handler(HeroAttributesInput(hero_id=999999), QueryContext())

    result, dispatch = asyncio.run(
        ToolExecutor(registry).execute(
            ToolCall(
                id="missing-hero",
                tool="dota.hero_attributes",
                args={"hero_id": 999999},
            ),
            QueryContext(),
        )
    )
    assert result.status == "error"
    assert result.error == "CatalogLookupError: hero not found: 999999"
    assert dispatch.error_code == "handler_error"


def test_hero_abilities_contract_preserves_catalog_order_and_fields() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )
    definition = registry.get("dota.hero_abilities")
    result = definition.handler(HeroAbilitiesInput(hero_id=25), QueryContext())
    repository = DotaCatalogRepository()
    lina = repository.get_hero(25)
    source_abilities = repository.get_hero_abilities(25)

    assert definition.source is not None
    assert definition.source.kind == "official_snapshot"
    assert definition.source.status == "committed_snapshot"
    assert definition.mandatory_evidence == ("hero_ability",)
    assert definition.metadata["domain"] == "hero_abilities"
    assert definition.arg_contracts["hero_id"].requires_reference is True
    accepted = definition.arg_contracts["hero_id"].accepts_refs
    assert [(item.from_tool, item.path, item.type) for item in accepted] == [
        ("resolve_hero", "data.hero.hero_id", "int")
    ]
    assert {item.path for item in definition.output_paths.values()} == {
        "data.hero",
        "data.abilities",
    }
    assert result["hero"]["hero_id"] == lina.hero_id
    assert result["hero"]["name"] == lina.internal_name
    assert [ability["ability_id"] for ability in result["abilities"]] == lina.ability_ids
    assert all(not ability["is_talent"] for ability in result["abilities"])
    assert result["snapshot"]["patch"] == "7.41e"

    for output, source in zip(result["abilities"], source_abilities, strict=True):
        assert output["internal_name"] == source.internal_name
        assert output["name_en"] == source.name_en
        assert output["name_zh"] == source.name_zh
        assert output["description_en"] == source.description_en
        assert output["notes_zh"] == source.notes_zh
        assert output["scepter_en"] == source.scepter_en
        assert output["shard_zh"] == source.shard_zh
        assert output["cooldowns"] == source.cooldowns
        assert output["mana_costs"] == source.mana_costs
        assert output["special_values"] == [
            value.model_dump(mode="json") for value in source.special_values
        ]
        assert output["is_innate"] == source.is_innate
        assert output["has_scepter"] == source.has_scepter
        assert output["has_shard"] == source.has_shard
        assert output["granted_by_scepter"] == source.granted_by_scepter
        assert output["granted_by_shard"] == source.granted_by_shard
        assert output["hero_ids"] == source.hero_ids
    assert any(
        ability["has_shard"] or ability["granted_by_scepter"]
        for ability in result["abilities"]
    )

    tool_result = ToolResult(
        tool_call_id="abilities",
        tool="dota.hero_abilities",
        status="ok",
        data=result,
        source=definition.source,
        latency_ms=0,
    )
    assert definition.evidence_extractor is not None
    evidence = definition.evidence_extractor(tool_result)
    assert [item.value["ability_id"] for item in evidence] == lina.ability_ids
    assert all(item.kind == "hero_ability" for item in evidence)
    assert all(item.tool_call_id == "abilities" for item in evidence)
    assert all(item.source == definition.source for item in evidence)
    assert all(item.value["hero_id"] == 25 for item in evidence)
    assert all(item.value["snapshot"]["patch"] == "7.41e" for item in evidence)

    malformed = tool_result.model_copy(update={"data": {"hero": {}, "abilities": "bad"}})
    assert definition.evidence_extractor(malformed) == []


def test_hero_abilities_requires_reference_and_exposes_unknown_id_error() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )
    literal_plan = ExecutionPlan(
        intent="hero_abilities",
        goal="Show Lina abilities.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="abilities", tool="dota.hero_abilities", args={"hero_id": 25})
        ],
        required_evidence=["hero_ability"],
    )
    errors = validate_plan_against_catalog(literal_plan, registry)
    assert (
        "dota.hero_abilities.hero_id must reference a previous current-plan tool result"
        in errors
    )

    referenced_plan = ExecutionPlan(
        intent="hero_abilities",
        goal="Show Lina abilities.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="resolve", tool="resolve_hero", args={"query": "Lina"}),
            ToolCall(
                id="abilities",
                tool="dota.hero_abilities",
                args={"hero_id": "$resolve.data.hero.hero_id"},
            ),
        ],
        required_evidence=["hero_identity", "hero_ability"],
    )
    assert validate_plan_against_catalog(referenced_plan, registry) == []

    result, dispatch = asyncio.run(
        ToolExecutor(registry).execute(
            ToolCall(
                id="missing-hero",
                tool="dota.hero_abilities",
                args={"hero_id": 999999},
            ),
            QueryContext(),
        )
    )
    assert result.status == "error"
    assert result.error == "CatalogLookupError: hero not found: 999999"
    assert dispatch.error_code == "handler_error"


def test_hero_talent_tree_contract_preserves_four_catalog_tiers() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )
    definition = registry.get("dota.hero_talent_tree")
    result = definition.handler(HeroTalentTreeInput(hero_id=25), QueryContext())
    repository = DotaCatalogRepository()
    lina = repository.get_hero(25)

    assert definition.source is not None
    assert definition.source.kind == "official_snapshot"
    assert definition.source.status == "committed_snapshot"
    assert definition.mandatory_evidence == ("hero_talent_tree",)
    assert definition.metadata["domain"] == "hero_talent_tree"
    assert definition.arg_contracts["hero_id"].requires_reference is True
    accepted = definition.arg_contracts["hero_id"].accepts_refs
    assert [(item.from_tool, item.path, item.type) for item in accepted] == [
        ("resolve_hero", "data.hero.hero_id", "int")
    ]
    assert {item.path for item in definition.output_paths.values()} == {
        "data.hero",
        "data.talent_tree",
    }
    assert result["hero"]["hero_id"] == 25
    assert result["hero"]["name"] == lina.internal_name
    assert [tier["level"] for tier in result["talent_tree"]] == [10, 15, 20, 25]
    assert result["snapshot"]["patch"] == "7.41e"

    for output, source in zip(result["talent_tree"], lina.talent_tiers, strict=True):
        assert output["level"] == source.level
        assert output["left"]["ability_id"] == source.left_ability_id
        assert output["right"]["ability_id"] == source.right_ability_id
        for side, ability_id in (
            ("left", source.left_ability_id),
            ("right", source.right_ability_id),
        ):
            talent = repository.get_ability(ability_id)
            branch = output[side]
            assert talent.is_talent is True
            assert branch["is_talent"] is True
            assert branch["internal_name"] == talent.internal_name
            assert branch["name_en"] == talent.name_en
            assert branch["name_zh"] == talent.name_zh
            assert branch["display_text"] == (talent.name_zh or talent.name_en)
            assert branch["special_values"] == [
                value.model_dump(mode="json") for value in talent.special_values
            ]

    tool_result = ToolResult(
        tool_call_id="talents",
        tool="dota.hero_talent_tree",
        status="ok",
        data=result,
        source=definition.source,
        latency_ms=0,
    )
    assert definition.evidence_extractor is not None
    evidence = definition.evidence_extractor(tool_result)
    assert len(evidence) == 8
    assert len({item.id for item in evidence}) == 8
    assert all(item.kind == "hero_talent_tree" for item in evidence)
    assert all(item.tool_call_id == "talents" for item in evidence)
    assert all(item.source == definition.source for item in evidence)
    assert all(item.value["hero_id"] == 25 for item in evidence)
    assert {item.value["level"] for item in evidence} == {10, 15, 20, 25}
    assert {item.value["side"] for item in evidence} == {"left", "right"}
    assert all(item.value["snapshot"]["patch"] == "7.41e" for item in evidence)

    malformed = tool_result.model_copy(update={"data": {"talent_tree": []}})
    assert definition.evidence_extractor(malformed) == []


def test_hero_talent_tree_requires_reference_and_exposes_unknown_id_error() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )
    literal_plan = ExecutionPlan(
        intent="hero_talent_tree",
        goal="Show Lina talents.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(
                id="talents",
                tool="dota.hero_talent_tree",
                args={"hero_id": 25},
            )
        ],
        required_evidence=["hero_talent_tree"],
    )
    errors = validate_plan_against_catalog(literal_plan, registry)
    assert (
        "dota.hero_talent_tree.hero_id must reference a previous current-plan tool result"
        in errors
    )

    referenced_plan = ExecutionPlan(
        intent="hero_talent_tree",
        goal="Show Lina talents.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="resolve", tool="resolve_hero", args={"query": "Lina"}),
            ToolCall(
                id="talents",
                tool="dota.hero_talent_tree",
                args={"hero_id": "$resolve.data.hero.hero_id"},
            ),
        ],
        required_evidence=["hero_identity", "hero_talent_tree"],
    )
    assert validate_plan_against_catalog(referenced_plan, registry) == []

    result, dispatch = asyncio.run(
        ToolExecutor(registry).execute(
            ToolCall(
                id="missing-hero",
                tool="dota.hero_talent_tree",
                args={"hero_id": 999999},
            ),
            QueryContext(),
        )
    )
    assert result.status == "error"
    assert result.error == "CatalogLookupError: hero not found: 999999"
    assert dispatch.error_code == "handler_error"


def test_resolve_item_preserves_main_item_recipe_scope_and_snapshot() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )
    definition = registry.get("resolve_item")

    main = definition.handler(ResolveItemInput(query="Black King Bar"), QueryContext())
    chinese = definition.handler(ResolveItemInput(query="黑皇杖"), QueryContext())
    recipe = definition.handler(
        ResolveItemInput(query="Black King Bar Recipe"), QueryContext()
    )
    missing = definition.handler(ResolveItemInput(query="missing item"), QueryContext())
    excluded = definition.handler(ResolveItemInput(query="item_ascetic_cap"), QueryContext())

    assert main["status"] == "resolved"
    assert main["method"] == "exact"
    assert main["item"]["item_id"] == 116
    assert main["item"]["is_recipe"] is False
    assert chinese["item"]["item_id"] == 116
    assert recipe["status"] == "resolved"
    assert recipe["item"]["item_id"] == 115
    assert recipe["item"]["is_recipe"] is True
    assert missing["status"] == "not_found"
    assert excluded["status"] == "not_found"
    assert main["snapshot"]["patch"] == "7.41e"
    assert definition.source is not None
    assert definition.source.kind == "official_snapshot"
    assert definition.mandatory_evidence == ("item_identity",)
    assert definition.output_paths["item_id"].path == "data.item.item_id"

    tool_result = ToolResult(
        tool_call_id="resolve-item",
        tool="resolve_item",
        status="ok",
        data=main,
        source=definition.source,
        latency_ms=0,
    )
    assert definition.evidence_extractor is not None
    evidence = definition.evidence_extractor(tool_result)
    assert len(evidence) == 1
    assert evidence[0].id == "resolve-item:item_identity:116"
    assert evidence[0].kind == "item_identity"
    assert evidence[0].tool_call_id == "resolve-item"
    assert evidence[0].source == definition.source
    assert evidence[0].value["snapshot"]["patch"] == "7.41e"


def test_item_info_contract_fields_and_recipe_evidence() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )
    definition = registry.get("dota.item_info")
    repository = DotaCatalogRepository()
    bkb = repository.get_item(116)
    result = definition.handler(ItemInfoInput(item_id=116), QueryContext())

    assert definition.source is not None
    assert definition.source.kind == "official_snapshot"
    assert definition.mandatory_evidence == ("item_definition",)
    assert definition.evidence_kinds == ("item_definition", "item_recipe")
    assert definition.metadata["domain"] == "item_info"
    assert definition.arg_contracts["item_id"].requires_reference is True
    accepted = definition.arg_contracts["item_id"].accepts_refs
    assert [(item.from_tool, item.path, item.type) for item in accepted] == [
        ("resolve_item", "data.item.item_id", "int")
    ]
    assert {item.path for item in definition.output_paths.values()} == {
        "data.item",
        "data.recipe",
    }
    assert result["item"]["item_id"] == 116
    assert result["item"]["description_en"] == bkb.description_en
    assert result["item"]["description_zh"] == bkb.description_zh
    assert result["item"]["notes_en"] == bkb.notes_en
    assert result["item"]["price"] == bkb.price
    assert result["item"]["special_values"] == [
        value.model_dump(mode="json") for value in bkb.special_values
    ]
    assert result["item"]["recipe_component_ids"] == bkb.recipe_component_ids
    assert result["item"]["is_recipe"] is False
    assert result["recipe"]["component_item_ids"] == bkb.recipe_component_ids
    assert result["recipe"]["upgrade_item_ids"] == []
    assert [item["item_id"] for item in result["recipe"]["component_items"]] == [
        8,
        21,
    ]
    assert result["snapshot"]["patch"] == "7.41e"

    tool_result = ToolResult(
        tool_call_id="item-info",
        tool="dota.item_info",
        status="ok",
        data=result,
        source=definition.source,
        latency_ms=0,
    )
    assert definition.evidence_extractor is not None
    evidence = definition.evidence_extractor(tool_result)
    assert [item.kind for item in evidence] == ["item_definition", "item_recipe"]
    assert len({item.id for item in evidence}) == 2
    assert all(item.tool_call_id == "item-info" for item in evidence)
    assert all(item.source == definition.source for item in evidence)
    assert all(item.value["snapshot"]["patch"] == "7.41e" for item in evidence)
    assert evidence[1].value["component_item_ids"] == [8, 21]

    recipe_result = definition.handler(ItemInfoInput(item_id=115), QueryContext())
    assert recipe_result["item"]["is_recipe"] is True
    assert recipe_result["recipe"]["component_item_ids"] == [8, 21]
    assert recipe_result["recipe"]["upgrade_item_ids"] == [116]


def test_item_info_omits_recipe_evidence_without_graph_and_rejects_bad_ids() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )
    definition = registry.get("dota.item_info")
    result = definition.handler(ItemInfoInput(item_id=257), QueryContext())
    assert "recipe" not in result

    tool_result = ToolResult(
        tool_call_id="item-info",
        tool="dota.item_info",
        status="ok",
        data=result,
        source=definition.source,
        latency_ms=0,
    )
    assert definition.evidence_extractor is not None
    evidence = definition.evidence_extractor(tool_result)
    assert [item.kind for item in evidence] == ["item_definition"]

    literal_plan = ExecutionPlan(
        intent="item_info",
        goal="Show BKB.",
        output_contract="natural_language_answer",
        tool_calls=[ToolCall(id="info", tool="dota.item_info", args={"item_id": 116})],
        required_evidence=["item_definition"],
    )
    errors = validate_plan_against_catalog(literal_plan, registry)
    assert (
        "dota.item_info.item_id must reference a previous current-plan tool result"
        in errors
    )
    referenced_plan = ExecutionPlan(
        intent="item_info",
        goal="Show BKB.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="resolve", tool="resolve_item", args={"query": "Black King Bar"}),
            ToolCall(
                id="info",
                tool="dota.item_info",
                args={"item_id": "$resolve.data.item.item_id"},
            ),
        ],
        required_evidence=["item_identity", "item_definition"],
    )
    assert validate_plan_against_catalog(referenced_plan, registry) == []

    error, dispatch = asyncio.run(
        ToolExecutor(registry).execute(
            ToolCall(id="missing", tool="dota.item_info", args={"item_id": 999999}),
            QueryContext(),
        )
    )
    assert error.status == "error"
    assert error.error == "CatalogLookupError: item not found: 999999"
    assert dispatch.error_code == "handler_error"


def test_item_info_shivas_recipe_definitions_and_cost_breakdown_are_complete() -> None:
    registry = build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )
    definition = registry.get("dota.item_info")

    result = definition.handler(ItemInfoInput(item_id=119), QueryContext())
    recipe = result["recipe"]

    assert [(item["item_id"], item["price"]) for item in recipe["recipe_items"]] == [
        (118, 1250)
    ]
    assert [
        (item["item_id"], item["name_en"], item["name_zh"], item["price"])
        for item in recipe["component_items"]
    ] == [
        (9, "Platemail", "板甲", 1400),
        (1847, "Splintmail", "片甲", 950),
        (1872, "Chasm Stone", "裂隙之石", 900),
    ]
    assert all("special_values" in item for item in recipe["recipe_items"])
    assert all("special_values" in item for item in recipe["component_items"])
    assert recipe["upgrade_items"] == []
    assert [(item["item_id"], item["price"]) for item in recipe["edges"][0]["upgrade_items"]] == [
        (119, 4500)
    ]
    breakdown = recipe["edges"][0]["cost_breakdown"]
    assert breakdown == {
        "component_price_total": 3250,
        "recipe_price_total": 1250,
        "calculated_total_price": 4500,
        "finished_items": [{"item_id": 119, "price": 4500, "is_consistent": True}],
    }

    tool_result = ToolResult(
        tool_call_id="shiva-info",
        tool="dota.item_info",
        status="ok",
        data=result,
        source=definition.source,
        latency_ms=0,
    )
    assert definition.evidence_extractor is not None
    evidence = definition.evidence_extractor(tool_result)
    recipe_evidence = next(item for item in evidence if item.kind == "item_recipe")
    assert recipe_evidence.value["recipe"]["recipe_items"][0]["item_id"] == 118
    assert recipe_evidence.value["recipe"]["edges"][0]["cost_breakdown"] == breakdown


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
        "dota.hero_attributes": ("hero_attributes",),
        "dota.hero_abilities": ("hero_ability",),
        "dota.hero_talent_tree": ("hero_talent_tree",),
        "resolve_item": ("item_identity",),
        "dota.item_info": ("item_definition",),
        "stratz.pair_lane_outcome": ("pair_lane_outcome",),
        "stratz.hero_matchup_ranking": ("matchup_ranking_row",),
        "stratz.hero_synergy_ranking": ("hero_synergy_ranking_row",),
        "stratz.lane_meta_global": ("lane_meta_row",),
        "stratz.hero_position_stats": ("position_stat",),
        "stratz.hero_daily_trends": ("hero_daily_trend",),
        "stratz.filter_ranked_heroes_by_position": ("role_filtered_candidate_row",),
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
