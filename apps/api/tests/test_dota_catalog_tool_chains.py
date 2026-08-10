from __future__ import annotations

import asyncio
import json

from app.agentic.models import ExecutionPlan, ToolCall
from app.agentic.nodes import evidence_node, run_init_node, tool_executor_node
from app.agentic.planning.contracts import (
    render_controller_tools,
    validate_plan_against_catalog,
    validate_registry_contracts,
)
from app.agentic.planning.decisions import resolve_required_evidence
from app.agentic.runtime.clock import SystemClock
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolExecutor
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import RuntimePolicy, Settings

CATALOG_TOOLS = {
    "resolve_hero": {
        "evidence": ("hero_identity",),
        "mandatory": ("hero_identity",),
        "outputs": {"data.hero.hero_id"},
        "domain": "hero_identity",
    },
    "dota.hero_attributes": {
        "evidence": ("hero_attributes",),
        "mandatory": ("hero_attributes",),
        "outputs": {"data.hero", "data.attributes", "data.combat"},
        "domain": "hero_attributes",
    },
    "dota.hero_abilities": {
        "evidence": ("hero_ability",),
        "mandatory": ("hero_ability",),
        "outputs": {"data.hero", "data.abilities"},
        "domain": "hero_abilities",
    },
    "dota.hero_talent_tree": {
        "evidence": ("hero_talent_tree",),
        "mandatory": ("hero_talent_tree",),
        "outputs": {"data.hero", "data.talent_tree"},
        "domain": "hero_talent_tree",
    },
    "resolve_item": {
        "evidence": ("item_identity",),
        "mandatory": ("item_identity",),
        "outputs": {"data.item.item_id"},
        "domain": "item_identity",
    },
    "dota.item_info": {
        "evidence": ("item_definition", "item_recipe"),
        "mandatory": ("item_definition",),
        "outputs": {"data.item", "data.recipe"},
        "domain": "item_info",
    },
}


def _registry():
    return build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )


def _execute_to_evidence(plan: ExecutionPlan):
    registry = _registry()
    state = AgentRunState(query=plan.goal, game="dota2", plan=plan)
    resolution = resolve_required_evidence(plan, registry)
    state.effective_required_evidence = resolution.effective_required_evidence
    state.global_required_evidence = resolution.global_required_evidence
    state.mandatory_evidence_by_call = resolution.mandatory_evidence_by_call
    clock = SystemClock()
    run_init_node(state, RuntimePolicy(), clock)
    state = asyncio.run(tool_executor_node(state, ToolExecutor(registry), clock))
    evidence_node(state, registry)
    return state


def _hero_plan() -> ExecutionPlan:
    return ExecutionPlan(
        intent="hero_catalog",
        goal="Load Lina attributes, abilities, and talents.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="hero", tool="resolve_hero", args={"query": "Lina"}),
            ToolCall(
                id="attributes",
                tool="dota.hero_attributes",
                args={"hero_id": "$hero.data.hero.hero_id"},
            ),
            ToolCall(
                id="abilities",
                tool="dota.hero_abilities",
                args={"hero_id": "$hero.data.hero.hero_id"},
            ),
            ToolCall(
                id="talents",
                tool="dota.hero_talent_tree",
                args={"hero_id": "$hero.data.hero.hero_id"},
            ),
        ],
        required_evidence=[
            "hero_identity",
            "hero_attributes",
            "hero_ability",
            "hero_talent_tree",
        ],
    )


def _item_plan(query: str, *, require_recipe: bool) -> ExecutionPlan:
    required = ["item_identity", "item_definition"]
    if require_recipe:
        required.append("item_recipe")
    return ExecutionPlan(
        intent="item_catalog",
        goal=f"Load static item information for {query}.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="item", tool="resolve_item", args={"query": query}),
            ToolCall(
                id="info",
                tool="dota.item_info",
                args={"item_id": "$item.data.item.item_id"},
            ),
        ],
        required_evidence=required,
    )


def test_catalog_registry_has_exactly_one_of_each_v33_tool_contract() -> None:
    registry = _registry()
    names = [definition.name for definition in registry.list()]

    assert validate_registry_contracts(registry) == []
    for name, expected in CATALOG_TOOLS.items():
        assert names.count(name) == 1
        definition = registry.get(name)
        assert definition.evidence_kinds == expected["evidence"]
        assert definition.mandatory_evidence == expected["mandatory"]
        assert {value.path for value in definition.output_paths.values()} == expected[
            "outputs"
        ]
        assert definition.metadata["domain"] == expected["domain"]
        assert definition.metadata["snapshot"] is True
        assert definition.source is not None
        assert definition.source.name == "Valve Dota 2 Datafeed snapshot"
        assert definition.source.kind == "official_snapshot"
        assert definition.source.url == "https://www.dota2.com/datafeed"
        assert definition.source.status == "committed_snapshot"

    for name in (
        "dota.hero_attributes",
        "dota.hero_abilities",
        "dota.hero_talent_tree",
    ):
        contract = registry.get(name).arg_contracts["hero_id"]
        assert contract.requires_reference is True
        assert [(ref.from_tool, ref.path, ref.type) for ref in contract.accepts_refs] == [
            ("resolve_hero", "data.hero.hero_id", "int")
        ]
    item_contract = registry.get("dota.item_info").arg_contracts["item_id"]
    assert item_contract.requires_reference is True
    assert [(ref.from_tool, ref.path, ref.type) for ref in item_contract.accepts_refs] == [
        ("resolve_item", "data.item.item_id", "int")
    ]


def test_catalog_renderer_exposes_six_tools_and_reference_schema() -> None:
    rendered = render_controller_tools(_registry())

    for name in CATALOG_TOOLS:
        assert rendered.count(f"- {name}\n") == 1
    assert "resolve_hero.data.hero.hero_id (int)" in rendered
    assert "resolve_item.data.item.item_id (int)" in rendered
    assert "data.talent_tree: list[dict]" in rendered
    assert 'evidence_produced: ["item_definition", "item_recipe"]' in rendered


def test_catalog_validate_plan_accepts_chains_and_rejects_invalid_references() -> None:
    registry = _registry()
    assert validate_plan_against_catalog(_hero_plan(), registry) == []
    assert validate_plan_against_catalog(
        _item_plan("Black King Bar", require_recipe=True), registry
    ) == []

    literal = _hero_plan()
    literal.tool_calls[1].args = {"hero_id": 25}
    assert any(
        "must reference a previous current-plan tool result" in error
        for error in validate_plan_against_catalog(literal, registry)
    )

    wrong_tool = ExecutionPlan(
        intent="item_catalog",
        goal="Reject a hero reference passed to item info.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="hero", tool="resolve_hero", args={"query": "Lina"}),
            ToolCall(
                id="info",
                tool="dota.item_info",
                args={"item_id": "$hero.data.hero.hero_id"},
            ),
        ],
        required_evidence=["item_definition"],
    )
    assert any(
        "does not accept reference from resolve_hero" in error
        for error in validate_plan_against_catalog(wrong_tool, registry)
    )

    wrong_path = _item_plan("Black King Bar", require_recipe=False)
    wrong_path.tool_calls[1].args = {"item_id": "$item.data.item.missing"}
    assert any(
        "reference path is not declared" in error
        for error in validate_plan_against_catalog(wrong_path, registry)
    )

    forward = _hero_plan()
    forward.tool_calls = [forward.tool_calls[1], forward.tool_calls[0]]
    assert any(
        "reference target must be a previous tool call" in error
        for error in validate_plan_against_catalog(forward, registry)
    )


def test_catalog_hero_chain_executes_refs_and_builds_complete_evidence_graph() -> None:
    state = _execute_to_evidence(_hero_plan())

    assert state.status == "ok"
    assert [result.status for result in state.tool_results] == ["ok"] * 4
    assert state.tool_results[0].data["hero"]["hero_id"] == 25
    assert state.tool_results[1].data["hero"]["hero_id"] == 25
    assert state.tool_results[2].data["hero"]["hero_id"] == 25
    assert state.tool_results[3].data["hero"]["hero_id"] == 25
    assert state.evidence_graph is not None
    assert state.evidence_graph.missing == []
    assert state.evidence_graph.mandatory_evidence_by_call == {
        "hero": ["hero_identity"],
        "attributes": ["hero_attributes"],
        "abilities": ["hero_ability"],
        "talents": ["hero_talent_tree"],
    }
    kinds = [item.kind for item in state.evidence_graph.evidence]
    assert kinds.count("hero_identity") == 1
    assert kinds.count("hero_attributes") == 1
    assert kinds.count("hero_ability") == 6
    assert kinds.count("hero_talent_tree") == 8

    for result in state.tool_results:
        assert result.source is not None
        assert result.source.kind == "official_snapshot"
        assert result.data["snapshot"]["patch"] == "7.41e"
        serialized = json.dumps(
            {"source": result.source.model_dump(), "snapshot": result.data["snapshot"]}
        )
        assert "snapshot_dir" not in serialized
        assert "D:\\" not in serialized


def test_catalog_item_chain_and_optional_recipe_evidence_follow_actual_graph() -> None:
    bkb_state = _execute_to_evidence(_item_plan("Black King Bar", require_recipe=True))
    assert bkb_state.status == "ok"
    assert bkb_state.tool_results[0].data["item"]["item_id"] == 116
    assert bkb_state.tool_results[1].data["item"]["item_id"] == 116
    assert bkb_state.evidence_graph is not None
    assert bkb_state.evidence_graph.missing == []
    assert bkb_state.evidence_graph.mandatory_evidence_by_call == {
        "item": ["item_identity"],
        "info": ["item_definition"],
    }
    assert [item.kind for item in bkb_state.evidence_graph.evidence] == [
        "item_identity",
        "item_definition",
        "item_recipe",
    ]
    for result in bkb_state.tool_results:
        assert result.source is not None
        assert result.source.kind == "official_snapshot"
        assert result.data["snapshot"]["patch"] == "7.41e"
        serialized = json.dumps(
            {"source": result.source.model_dump(), "snapshot": result.data["snapshot"]}
        )
        assert "snapshot_dir" not in serialized
        assert "D:\\" not in serialized

    tome_state = _execute_to_evidence(
        _item_plan("Tome of Knowledge", require_recipe=False)
    )
    assert tome_state.evidence_graph is not None
    assert tome_state.evidence_graph.missing == []
    assert [item.kind for item in tome_state.evidence_graph.evidence] == [
        "item_identity",
        "item_definition",
    ]

    missing_recipe = _execute_to_evidence(
        _item_plan("Tome of Knowledge", require_recipe=True)
    )
    assert missing_recipe.evidence_graph is not None
    assert "item_recipe" in missing_recipe.evidence_graph.missing
