"""Agent tool registration for the committed Valve static catalog."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agentic.evidence import EvidenceItem
from app.agentic.models import QueryContext, ToolResult, ToolSource
from app.agentic.tools import (
    AcceptedRef,
    ArgContract,
    OutputPathContract,
    ToolDefinition,
    ToolRegistry,
)
from app.integrations.valve.catalog_repository import (
    CATALOG_IMAGE_BASE_PATH,
    CatalogSnapshotError,
    DotaCatalogRepository,
    load_default_catalog_repository,
)
from app.integrations.valve.datafeed import DATAFEED_ROOT


class ResolveHeroInput(BaseModel):
    query: str = Field(min_length=1)


class HeroAttributesInput(BaseModel):
    hero_id: int = Field(gt=0)


class HeroAbilitiesInput(BaseModel):
    hero_id: int = Field(gt=0)


class HeroTalentTreeInput(BaseModel):
    hero_id: int = Field(gt=0)


class ResolveItemInput(BaseModel):
    query: str = Field(min_length=1)


class ItemInfoInput(BaseModel):
    item_id: int = Field(gt=0)


def register_dota_catalog_tools(
    registry: ToolRegistry,
    repository: DotaCatalogRepository | None = None,
) -> None:
    catalog = repository or load_default_catalog_repository()
    registry.register(
        ToolDefinition(
            name="resolve_hero",
            description=(
                "Resolve a Dota 2 hero name, localized name, internal name, or "
                "alias to a canonical hero id from the committed Valve catalog. "
                "Returns resolved, ambiguous, or not_found without querying a network."
            ),
            input_model=ResolveHeroInput,
            handler=_resolve_hero_handler(catalog),
            source=ToolSource(
                name="Valve Dota 2 Datafeed snapshot",
                kind="official_snapshot",
                url=DATAFEED_ROOT,
                status="committed_snapshot",
            ),
            evidence_extractor=resolve_hero_evidence,
            evidence_kinds=("hero_identity",),
            mandatory_evidence=("hero_identity",),
            arg_contracts={
                "query": ArgContract(description="Hero name, internal name, or alias."),
            },
            output_paths={
                "hero_id": OutputPathContract(
                    path="data.hero.hero_id",
                    type="int",
                    description="Canonical Dota 2 hero id.",
                ),
            },
            metadata={"game": "dota2", "domain": "hero_identity", "snapshot": True},
        )
    )
    registry.register(
        ToolDefinition(
            name="dota.hero_attributes",
            description=(
                "Return a hero's official static attributes and combat fields from "
                "the committed Valve catalog snapshot."
            ),
            input_model=HeroAttributesInput,
            handler=_hero_attributes_handler(catalog),
            source=ToolSource(
                name="Valve Dota 2 Datafeed snapshot",
                kind="official_snapshot",
                url=DATAFEED_ROOT,
                status="committed_snapshot",
            ),
            evidence_extractor=hero_attributes_evidence,
            evidence_kinds=("hero_attributes",),
            mandatory_evidence=("hero_attributes",),
            arg_contracts={
                "hero_id": ArgContract(
                    description="Canonical Dota 2 hero id.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="resolve_hero",
                            path="data.hero.hero_id",
                            type="int",
                        ),
                    ),
                    requires_reference=True,
                ),
            },
            output_paths={
                "hero": OutputPathContract(
                    path="data.hero",
                    type="dict",
                    description="Canonical hero identity.",
                ),
                "attributes": OutputPathContract(
                    path="data.attributes",
                    type="dict",
                    description="Official primary and base attribute fields.",
                ),
                "combat": OutputPathContract(
                    path="data.combat",
                    type="dict",
                    description="Official static combat and movement fields.",
                ),
            },
            metadata={
                "game": "dota2",
                "domain": "hero_attributes",
                "snapshot": True,
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="dota.hero_abilities",
            description=(
                "Return a hero's ordered non-talent ability definitions from the "
                "committed Valve catalog snapshot."
            ),
            input_model=HeroAbilitiesInput,
            handler=_hero_abilities_handler(catalog),
            source=ToolSource(
                name="Valve Dota 2 Datafeed snapshot",
                kind="official_snapshot",
                url=DATAFEED_ROOT,
                status="committed_snapshot",
            ),
            evidence_extractor=hero_abilities_evidence,
            evidence_kinds=("hero_ability",),
            mandatory_evidence=("hero_ability",),
            arg_contracts={
                "hero_id": ArgContract(
                    description="Canonical Dota 2 hero id.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="resolve_hero",
                            path="data.hero.hero_id",
                            type="int",
                        ),
                    ),
                    requires_reference=True,
                ),
            },
            output_paths={
                "hero": OutputPathContract(
                    path="data.hero",
                    type="dict",
                    description="Canonical hero identity.",
                ),
                "abilities": OutputPathContract(
                    path="data.abilities",
                    type="list[dict]",
                    description="Ordered non-talent ability definitions.",
                ),
            },
            metadata={
                "game": "dota2",
                "domain": "hero_abilities",
                "snapshot": True,
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="dota.hero_talent_tree",
            description=(
                "Return a hero's ordered level 10/15/20/25 talent tree from the "
                "committed Valve catalog snapshot."
            ),
            input_model=HeroTalentTreeInput,
            handler=_hero_talent_tree_handler(catalog),
            source=ToolSource(
                name="Valve Dota 2 Datafeed snapshot",
                kind="official_snapshot",
                url=DATAFEED_ROOT,
                status="committed_snapshot",
            ),
            evidence_extractor=hero_talent_tree_evidence,
            evidence_kinds=("hero_talent_tree",),
            mandatory_evidence=("hero_talent_tree",),
            arg_contracts={
                "hero_id": ArgContract(
                    description="Canonical Dota 2 hero id.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="resolve_hero",
                            path="data.hero.hero_id",
                            type="int",
                        ),
                    ),
                    requires_reference=True,
                ),
            },
            output_paths={
                "hero": OutputPathContract(
                    path="data.hero",
                    type="dict",
                    description="Canonical hero identity.",
                ),
                "talent_tree": OutputPathContract(
                    path="data.talent_tree",
                    type="list[dict]",
                    description="Ordered level 10/15/20/25 talent tiers.",
                ),
            },
            metadata={
                "game": "dota2",
                "domain": "hero_talent_tree",
                "snapshot": True,
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="resolve_item",
            description=(
                "Resolve a Dota 2 item name, localized name, internal name, or alias "
                "to a canonical item id from the committed Valve catalog. Explicit "
                "recipe wording selects recipe scope."
            ),
            input_model=ResolveItemInput,
            handler=_resolve_item_handler(catalog),
            source=ToolSource(
                name="Valve Dota 2 Datafeed snapshot",
                kind="official_snapshot",
                url=DATAFEED_ROOT,
                status="committed_snapshot",
            ),
            evidence_extractor=resolve_item_evidence,
            evidence_kinds=("item_identity",),
            mandatory_evidence=("item_identity",),
            arg_contracts={
                "query": ArgContract(description="Item name, internal name, or alias."),
            },
            output_paths={
                "item_id": OutputPathContract(
                    path="data.item.item_id",
                    type="int",
                    description="Canonical Dota 2 item id.",
                ),
            },
            metadata={"game": "dota2", "domain": "item_identity", "snapshot": True},
        )
    )
    registry.register(
        ToolDefinition(
            name="dota.item_info",
            description=(
                "Return an item's official static definition and available recipe "
                "relationships from the committed Valve catalog snapshot. Recipe "
                "evidence is produced only when the resolved item has component or "
                "upgrade relationships."
            ),
            input_model=ItemInfoInput,
            handler=_item_info_handler(catalog),
            source=ToolSource(
                name="Valve Dota 2 Datafeed snapshot",
                kind="official_snapshot",
                url=DATAFEED_ROOT,
                status="committed_snapshot",
            ),
            evidence_extractor=item_info_evidence,
            evidence_kinds=("item_definition", "item_recipe"),
            mandatory_evidence=("item_definition",),
            arg_contracts={
                "item_id": ArgContract(
                    description="Canonical Dota 2 item id.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="resolve_item",
                            path="data.item.item_id",
                            type="int",
                        ),
                    ),
                    requires_reference=True,
                ),
            },
            output_paths={
                "item": OutputPathContract(
                    path="data.item",
                    type="dict",
                    description="Official static item definition.",
                ),
                "recipe": OutputPathContract(
                    path="data.recipe",
                    type="dict",
                    description="Recipe relationships when present.",
                ),
            },
            metadata={"game": "dota2", "domain": "item_info", "snapshot": True},
        )
    )


def _resolve_hero_handler(repository: DotaCatalogRepository):
    def handle(args: ResolveHeroInput, _context: QueryContext) -> dict[str, Any]:
        result = repository.resolve_hero(args.query)
        result["snapshot"] = repository.snapshot_metadata()
        return result

    return handle


def _hero_attributes_handler(repository: DotaCatalogRepository):
    def handle(args: HeroAttributesInput, _context: QueryContext) -> dict[str, Any]:
        hero = repository.get_hero(args.hero_id)
        return {
            "hero": {
                "hero_id": hero.hero_id,
                "name": hero.internal_name,
                "name_en": hero.name_en,
                "name_zh": hero.name_zh,
                "aliases": list(hero.aliases),
                "image_path": f"{CATALOG_IMAGE_BASE_PATH}/heroes/{hero.hero_id}.png",
            },
            "attributes": {
                "primary_attribute": hero.primary_attribute,
                "complexity": hero.complexity,
                "role_levels": list(hero.role_levels),
                "strength_base": hero.strength_base,
                "strength_gain": hero.strength_gain,
                "agility_base": hero.agility_base,
                "agility_gain": hero.agility_gain,
                "intelligence_base": hero.intelligence_base,
                "intelligence_gain": hero.intelligence_gain,
            },
            "combat": {
                "attack_capability": hero.attack_capability,
                "damage_min": hero.damage_min,
                "damage_max": hero.damage_max,
                "attack_rate": hero.attack_rate,
                "attack_range": hero.attack_range,
                "projectile_speed": hero.projectile_speed,
                "armor": hero.armor,
                "magic_resistance": hero.magic_resistance,
                "movement_speed": hero.movement_speed,
                "turn_rate": hero.turn_rate,
                "sight_range_day": hero.sight_range_day,
                "sight_range_night": hero.sight_range_night,
                "max_health": hero.max_health,
                "health_regen": hero.health_regen,
                "max_mana": hero.max_mana,
                "mana_regen": hero.mana_regen,
            },
            "snapshot": repository.snapshot_metadata(),
        }

    return handle


def _hero_abilities_handler(repository: DotaCatalogRepository):
    def handle(args: HeroAbilitiesInput, _context: QueryContext) -> dict[str, Any]:
        hero = repository.get_hero(args.hero_id)
        abilities = [
            _serialize_hero_ability(ability)
            for ability in repository.get_hero_abilities(args.hero_id)
            if not ability.is_talent
        ]
        return {
            "hero": {
                "hero_id": hero.hero_id,
                "name": hero.internal_name,
                "name_en": hero.name_en,
                "name_zh": hero.name_zh,
                "aliases": list(hero.aliases),
                "image_path": f"{CATALOG_IMAGE_BASE_PATH}/heroes/{hero.hero_id}.png",
            },
            "abilities": abilities,
            "snapshot": repository.snapshot_metadata(),
        }

    return handle


def _serialize_hero_ability(ability: Any) -> dict[str, Any]:
    return {
        "ability_id": ability.ability_id,
        "internal_name": ability.internal_name,
        "name_en": ability.name_en,
        "name_zh": ability.name_zh,
        "description_en": ability.description_en,
        "description_zh": ability.description_zh,
        "lore_en": ability.lore_en,
        "lore_zh": ability.lore_zh,
        "notes_en": list(ability.notes_en),
        "notes_zh": list(ability.notes_zh),
        "scepter_en": ability.scepter_en,
        "scepter_zh": ability.scepter_zh,
        "shard_en": ability.shard_en,
        "shard_zh": ability.shard_zh,
        "behavior": ability.behavior,
        "target_team": ability.target_team,
        "target_type": ability.target_type,
        "flags": ability.flags,
        "damage": ability.damage,
        "immunity": ability.immunity,
        "dispellable": ability.dispellable,
        "max_level": ability.max_level,
        "cast_ranges": list(ability.cast_ranges),
        "cast_points": list(ability.cast_points),
        "channel_times": list(ability.channel_times),
        "cooldowns": list(ability.cooldowns),
        "durations": list(ability.durations),
        "damages": list(ability.damages),
        "mana_costs": list(ability.mana_costs),
        "gold_costs": list(ability.gold_costs),
        "health_costs": list(ability.health_costs),
        "special_values": [
            special.model_dump(mode="json") for special in ability.special_values
        ],
        "is_innate": ability.is_innate,
        "has_scepter": ability.has_scepter,
        "has_shard": ability.has_shard,
        "granted_by_scepter": ability.granted_by_scepter,
        "granted_by_shard": ability.granted_by_shard,
        "is_talent": ability.is_talent,
        "hero_ids": list(ability.hero_ids),
    }


def _hero_talent_tree_handler(repository: DotaCatalogRepository):
    def handle(args: HeroTalentTreeInput, _context: QueryContext) -> dict[str, Any]:
        hero = repository.get_hero(args.hero_id)
        tiers = repository.get_hero_talent_tree(args.hero_id)
        talent_tree: list[dict[str, Any]] = []
        for tier in tiers:
            left = repository.get_ability(tier.left_ability_id)
            right = repository.get_ability(tier.right_ability_id)
            if not left.is_talent or not right.is_talent:
                raise CatalogSnapshotError(
                    f"hero {hero.hero_id} talent tier {tier.level} contains non-talent ability"
                )
            talent_tree.append(
                {
                    "level": tier.level,
                    "left": _serialize_talent(left),
                    "right": _serialize_talent(right),
                }
            )
        return {
            "hero": {
                "hero_id": hero.hero_id,
                "name": hero.internal_name,
                "name_en": hero.name_en,
                "name_zh": hero.name_zh,
                "aliases": list(hero.aliases),
            },
            "talent_tree": talent_tree,
            "snapshot": repository.snapshot_metadata(),
        }

    return handle


def _serialize_talent(talent: Any) -> dict[str, Any]:
    return {
        "ability_id": talent.ability_id,
        "internal_name": talent.internal_name,
        "name_en": talent.name_en,
        "name_zh": talent.name_zh,
        "display_text": talent.name_zh or talent.name_en,
        "special_values": [
            special.model_dump(mode="json") for special in talent.special_values
        ],
        "is_talent": talent.is_talent,
        "hero_ids": list(talent.hero_ids),
    }


def _resolve_item_handler(repository: DotaCatalogRepository):
    def handle(args: ResolveItemInput, _context: QueryContext) -> dict[str, Any]:
        result = repository.resolve_item(args.query)
        result["snapshot"] = repository.snapshot_metadata()
        return result

    return handle


def _item_info_handler(repository: DotaCatalogRepository):
    def handle(args: ItemInfoInput, _context: QueryContext) -> dict[str, Any]:
        item = repository.get_item(args.item_id)
        payload: dict[str, Any] = {
            "item": _serialize_item(item),
            "snapshot": repository.snapshot_metadata(),
        }
        recipe_edges = repository.get_item_recipe_edges(args.item_id)
        if recipe_edges:
            serialized_edges = [
                _serialize_recipe_edge(repository, edge) for edge in recipe_edges
            ]
            payload["recipe"] = {
                "recipe_item_ids": _ordered_unique(
                    edge["recipe_item"]["item_id"] for edge in serialized_edges
                ),
                "component_item_ids": _ordered_unique(
                    item["item_id"]
                    for edge in serialized_edges
                    for item in edge["component_items"]
                ),
                "upgrade_item_ids": _ordered_unique(
                    item["item_id"]
                    for edge in serialized_edges
                    for item in edge["upgrade_items"]
                    if item["item_id"] != args.item_id
                ),
                "recipe_items": _ordered_unique_items(
                    edge["recipe_item"] for edge in serialized_edges
                ),
                "component_items": _ordered_unique_items(
                    item
                    for edge in serialized_edges
                    for item in edge["component_items"]
                ),
                "upgrade_items": _ordered_unique_items(
                    item
                    for edge in serialized_edges
                    for item in edge["upgrade_items"]
                    if item["item_id"] != args.item_id
                ),
                "edges": serialized_edges,
            }
        return payload

    return handle


def _serialize_item(item: Any) -> dict[str, Any]:
    return {
        **_serialize_item_identity(item),
        "aliases": list(item.aliases),
        "description_en": item.description_en,
        "description_zh": item.description_zh,
        "lore_en": item.lore_en,
        "lore_zh": item.lore_zh,
        "notes_en": list(item.notes_en),
        "notes_zh": list(item.notes_zh),
        "scepter_en": item.scepter_en,
        "scepter_zh": item.scepter_zh,
        "shard_en": item.shard_en,
        "shard_zh": item.shard_zh,
        "price": item.price,
        "quality": item.quality,
        "stock": item.stock,
        "initial_charges": item.initial_charges,
        "neutral_tier": item.neutral_tier,
        "behavior": item.behavior,
        "target_team": item.target_team,
        "target_type": item.target_type,
        "cooldowns": list(item.cooldowns),
        "durations": list(item.durations),
        "mana_costs": list(item.mana_costs),
        "health_costs": list(item.health_costs),
        "special_values": [
            special.model_dump(mode="json") for special in item.special_values
        ],
        "recipe_component_ids": list(item.recipe_component_ids),
        "upgrade_item_ids": list(item.upgrade_item_ids),
        "is_neutral": item.is_neutral,
        "is_purchasable": item.is_purchasable,
    }


def _serialize_item_identity(item: Any) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "name": item.internal_name,
        "name_en": item.name_en,
        "name_zh": item.name_zh,
        "is_recipe": item.is_recipe,
        "image_path": (
            None
            if item.is_recipe
            else f"{CATALOG_IMAGE_BASE_PATH}/items/{item.item_id}.png"
        ),
    }


def _serialize_item_recipe_definition(item: Any) -> dict[str, Any]:
    return {
        **_serialize_item_identity(item),
        "price": item.price,
        "special_values": [
            special.model_dump(mode="json") for special in item.special_values
        ],
    }


def _serialize_recipe_edge(repository: DotaCatalogRepository, edge: Any) -> dict[str, Any]:
    recipe_item = _serialize_item_recipe_definition(
        repository.get_item(edge.recipe_item_id)
    )
    component_items = [
        _serialize_item_recipe_definition(repository.get_item(item_id))
        for item_id in edge.component_item_ids
    ]
    upgrade_items = [
        _serialize_item_recipe_definition(repository.get_item(item_id))
        for item_id in edge.upgrade_item_ids
    ]
    component_total = _sum_known_prices(component_items)
    recipe_total = _sum_known_prices([recipe_item])
    calculated_total = (
        component_total + recipe_total
        if component_total is not None and recipe_total is not None
        else None
    )
    finished_items = [
        {
            "item_id": item["item_id"],
            "price": item["price"],
            "is_consistent": (
                calculated_total == item["price"]
                if calculated_total is not None and _is_numeric_price(item["price"])
                else None
            ),
        }
        for item in upgrade_items
    ]
    return {
        "recipe_item": recipe_item,
        "component_items": component_items,
        "upgrade_items": upgrade_items,
        "cost_breakdown": {
            "component_price_total": component_total,
            "recipe_price_total": recipe_total,
            "calculated_total_price": calculated_total,
            "finished_items": finished_items,
        },
    }


def _is_numeric_price(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _sum_known_prices(items: list[dict[str, Any]]) -> int | float | None:
    prices = [item.get("price") for item in items]
    if any(not _is_numeric_price(price) for price in prices):
        return None
    return sum(prices)


def _ordered_unique(values: Any) -> list[int]:
    return list(dict.fromkeys(int(value) for value in values))


def _ordered_unique_items(items: Any) -> list[dict[str, Any]]:
    by_id: dict[int, dict[str, Any]] = {}
    for item in items:
        by_id.setdefault(int(item["item_id"]), item)
    return list(by_id.values())


def resolve_hero_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    if data.get("status") != "resolved" or not isinstance(data.get("hero"), dict):
        return []

    hero = data["hero"]
    return [
        EvidenceItem(
            id=f"{result.tool_call_id}:hero_identity:{hero.get('hero_id')}",
            kind="hero_identity",
            subject=str(hero.get("localized_name") or hero.get("hero_id")),
            value={
                "hero_id": hero.get("hero_id"),
                "name": hero.get("name"),
                "name_en": hero.get("name_en"),
                "name_zh": hero.get("name_zh"),
                "localized_name": hero.get("localized_name"),
                "aliases": hero.get("aliases", []),
                "image_path": hero.get("image_path"),
                "method": data.get("method"),
                "query": data.get("query"),
                "snapshot": data.get("snapshot"),
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        )
    ]


def hero_attributes_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    hero = data.get("hero")
    attributes = data.get("attributes")
    combat = data.get("combat")
    snapshot = data.get("snapshot")
    if not all(isinstance(value, dict) for value in (hero, attributes, combat, snapshot)):
        return []

    return [
        EvidenceItem(
            id=f"{result.tool_call_id}:hero_attributes:{hero.get('hero_id')}",
            kind="hero_attributes",
            subject=str(hero.get("name_zh") or hero.get("name_en") or hero.get("hero_id")),
            value={
                "hero": dict(hero),
                "attributes": dict(attributes),
                "combat": dict(combat),
                "snapshot": dict(snapshot),
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        )
    ]


def hero_abilities_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    hero = data.get("hero")
    abilities = data.get("abilities")
    snapshot = data.get("snapshot")
    if (
        not isinstance(hero, dict)
        or not isinstance(abilities, list)
        or not isinstance(snapshot, dict)
    ):
        return []

    evidence: list[EvidenceItem] = []
    for ability in abilities:
        if not isinstance(ability, dict) or not isinstance(ability.get("ability_id"), int):
            return []
        evidence.append(
            EvidenceItem(
                id=(
                    f"{result.tool_call_id}:hero_ability:"
                    f"{hero.get('hero_id')}:{ability['ability_id']}"
                ),
                kind="hero_ability",
                subject=str(
                    ability.get("name_zh")
                    or ability.get("name_en")
                    or ability["ability_id"]
                ),
                value={
                    "hero_id": hero.get("hero_id"),
                    "ability_id": ability["ability_id"],
                    "ability": dict(ability),
                    "snapshot": dict(snapshot),
                },
                source=result.source,
                tool_call_id=result.tool_call_id,
                tool=result.tool,
            )
        )
    return evidence


def hero_talent_tree_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    hero = data.get("hero")
    talent_tree = data.get("talent_tree")
    snapshot = data.get("snapshot")
    if (
        not isinstance(hero, dict)
        or not isinstance(hero.get("hero_id"), int)
        or not isinstance(talent_tree, list)
        or len(talent_tree) != 4
        or not isinstance(snapshot, dict)
    ):
        return []

    evidence: list[EvidenceItem] = []
    for tier in talent_tree:
        if not isinstance(tier, dict) or not isinstance(tier.get("level"), int):
            return []
        level = tier["level"]
        for side in ("left", "right"):
            talent = tier.get(side)
            if (
                not isinstance(talent, dict)
                or not isinstance(talent.get("ability_id"), int)
                or talent.get("is_talent") is not True
            ):
                return []
            evidence.append(
                EvidenceItem(
                    id=(
                        f"{result.tool_call_id}:hero_talent_tree:{hero['hero_id']}:"
                        f"{level}:{side}:{talent['ability_id']}"
                    ),
                    kind="hero_talent_tree",
                    subject=str(
                        talent.get("display_text")
                        or talent.get("name_zh")
                        or talent.get("name_en")
                        or talent["ability_id"]
                    ),
                    value={
                        "hero_id": hero["hero_id"],
                        "talent_ability_id": talent["ability_id"],
                        "level": level,
                        "side": side,
                        "talent": dict(talent),
                        "snapshot": dict(snapshot),
                    },
                    source=result.source,
                    tool_call_id=result.tool_call_id,
                    tool=result.tool,
                )
            )
    return evidence


def resolve_item_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    item = data.get("item")
    snapshot = data.get("snapshot")
    if data.get("status") != "resolved" or not isinstance(item, dict):
        return []
    if not isinstance(item.get("item_id"), int) or not isinstance(snapshot, dict):
        return []

    return [
        EvidenceItem(
            id=f"{result.tool_call_id}:item_identity:{item['item_id']}",
            kind="item_identity",
            subject=str(item.get("localized_name") or item.get("name_en") or item["item_id"]),
            value={
                "item_id": item["item_id"],
                "name": item.get("name"),
                "name_en": item.get("name_en"),
                "name_zh": item.get("name_zh"),
                "localized_name": item.get("localized_name"),
                "aliases": item.get("aliases", []),
                "is_recipe": item.get("is_recipe"),
                "image_path": item.get("image_path"),
                "method": data.get("method"),
                "query": data.get("query"),
                "snapshot": dict(snapshot),
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        )
    ]


def item_info_evidence(result: ToolResult) -> list[EvidenceItem]:
    data = result.data if isinstance(result.data, dict) else {}
    item = data.get("item")
    snapshot = data.get("snapshot")
    if not isinstance(item, dict) or not isinstance(item.get("item_id"), int):
        return []
    if not isinstance(snapshot, dict):
        return []

    evidence = [
        EvidenceItem(
            id=f"{result.tool_call_id}:item_definition:{item['item_id']}",
            kind="item_definition",
            subject=str(item.get("name_zh") or item.get("name_en") or item["item_id"]),
            value={"item": dict(item), "snapshot": dict(snapshot)},
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        )
    ]
    recipe = data.get("recipe")
    if recipe is None:
        return evidence
    if not isinstance(recipe, dict):
        return []
    component_ids = recipe.get("component_item_ids")
    upgrade_ids = recipe.get("upgrade_item_ids")
    if not isinstance(component_ids, list) or not isinstance(upgrade_ids, list):
        return []
    if not component_ids and not upgrade_ids:
        return evidence
    evidence.append(
        EvidenceItem(
            id=f"{result.tool_call_id}:item_recipe:{item['item_id']}",
            kind="item_recipe",
            subject=str(item.get("name_zh") or item.get("name_en") or item["item_id"]),
            value={
                "item_id": item["item_id"],
                "component_item_ids": list(component_ids),
                "upgrade_item_ids": list(upgrade_ids),
                "recipe": dict(recipe),
                "snapshot": dict(snapshot),
            },
            source=result.source,
            tool_call_id=result.tool_call_id,
            tool=result.tool,
        )
    )
    return evidence
