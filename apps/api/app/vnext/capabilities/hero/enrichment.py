"""Hero-guide-specific field mapping onto the shared catalog resolver."""

from __future__ import annotations

from app.vnext.capabilities.hero.guide import HeroGuideResult
from app.vnext.catalog import (
    EntityKind,
    EntityNameResolution,
    EntityNameResolver,
    ResolvedEntityName,
)


def enrich_hero_guide(
    result: HeroGuideResult,
    resolver: EntityNameResolver,
) -> HeroGuideResult:
    """Add catalog names to the explicit entity fields in a projected guide."""

    hero_resolution = resolver.resolve_many(kind="hero", ids=[result.hero_id])
    resolutions: dict[EntityKind, EntityNameResolution] = {"hero": hero_resolution}

    item_ids = [
        item.item_id
        for guide in result.pub_guides
        for option in guide.starting_options
        for item in option.items
    ]
    item_ids.extend(
        item.item_id
        for guide in result.pub_guides
        for item in (*guide.item_progression, *guide.situational_items)
    )
    item_ids.extend(
        event.item_id
        for example in result.pro_examples
        for event in example.item_timeline
    )
    if item_ids:
        resolutions["item"] = resolver.resolve_many(kind="item", ids=item_ids)

    ability_ids = [
        ability_id
        for guide in result.pub_guides
        for sequence in guide.skill_sequences
        for ability_id in sequence.ability_ids
    ]
    ability_ids.extend(
        event.ability_id
        for example in result.pro_examples
        for event in example.ability_timeline
    )
    if ability_ids:
        resolutions["ability"] = resolver.resolve_many(kind="ability", ids=ability_ids)

    for resolution in resolutions.values():
        if resolution.catalog_version != hero_resolution.catalog_version:
            raise ValueError("catalog version changed during hero guide enrichment")

    result.hero_name = hero_resolution.entries[0].model_copy(deep=True)
    result.catalog_version = hero_resolution.catalog_version.model_copy(deep=True)
    item_names = _names_by_id(resolutions.get("item"))
    ability_names = _names_by_id(resolutions.get("ability"))

    for guide in result.pub_guides:
        for option in guide.starting_options:
            for item in option.items:
                item.resolved_name = item_names[item.item_id].model_copy(deep=True)
        for item in (*guide.item_progression, *guide.situational_items):
            item.resolved_name = item_names[item.item_id].model_copy(deep=True)
        for sequence in guide.skill_sequences:
            sequence.abilities = [
                ability_names[ability_id].model_copy(deep=True)
                for ability_id in sequence.ability_ids
            ]

    for example in result.pro_examples:
        for event in example.item_timeline:
            event.resolved_name = item_names[event.item_id].model_copy(deep=True)
        for event in example.ability_timeline:
            event.resolved_name = ability_names[event.ability_id].model_copy(deep=True)

    return result


def _names_by_id(
    resolution: EntityNameResolution | None,
) -> dict[int, ResolvedEntityName]:
    if resolution is None:
        return {}
    return {entry.id: entry for entry in resolution.entries}


__all__ = ["enrich_hero_guide"]
