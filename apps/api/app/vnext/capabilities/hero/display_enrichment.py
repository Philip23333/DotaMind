"""Attach local display references to visible, resolved Valve guide entities."""

from __future__ import annotations

from typing import Literal

from app.vnext.capabilities.hero.guide import (
    GuideItem,
    GuideItemObservation,
    HeroGuideResult,
    ProAbilityEvent,
    ProItemEvent,
    ProMatchExample,
    PubGuide,
    SkillSequenceOption,
    StartingItemOption,
)
from app.vnext.catalog import ResolvedEntityName
from app.vnext.entity_display import (
    EntityDisplayDirectory,
    EntityIdentity,
    make_display_ref,
)

_ValveKind = Literal["hero", "item", "ability"]
_Identity = tuple[_ValveKind, int]


def enrich_hero_guide_display_refs(
    result: HeroGuideResult,
    directory: EntityDisplayDirectory,
) -> HeroGuideResult:
    refs_by_identity: dict[_Identity, str] = {}
    _collect_name(result.hero_name, "hero", refs_by_identity)
    for guide in result.pub_guides:
        for option in guide.starting_options:
            for item in option.items:
                _collect_name(item.resolved_name, "item", refs_by_identity)
        for item in (*guide.item_progression, *guide.situational_items):
            _collect_name(item.resolved_name, "item", refs_by_identity)
        for sequence in guide.skill_sequences:
            for ability in sequence.abilities:
                _collect_name(ability, "ability", refs_by_identity)
    for example in result.pro_examples:
        for event in example.item_timeline:
            _collect_name(event.resolved_name, "item", refs_by_identity)
        for event in example.ability_timeline:
            _collect_name(event.resolved_name, "ability", refs_by_identity)

    refs_by_identity = _resolve_present_refs(refs_by_identity, directory)
    pub_guides = [_copy_pub_guide(guide, refs_by_identity) for guide in result.pub_guides]
    pro_examples = [
        _copy_pro_example(example, refs_by_identity) for example in result.pro_examples
    ]
    return result.model_copy(
        update={
            "hero_name": _copy_name(result.hero_name, "hero", refs_by_identity),
            "pub_guides": pub_guides,
            "pro_examples": pro_examples,
        }
    )


def _collect_name(
    name: ResolvedEntityName | None,
    kind: _ValveKind,
    refs: dict[_Identity, str],
) -> None:
    if name is None or name.status != "found" or name.id <= 0:
        return
    identity = (kind, name.id)
    refs.setdefault(
        identity,
        make_display_ref(
            EntityIdentity(source="valve", kind=kind, entity_id=name.id)
        ),
    )


def _resolve_present_refs(
    refs: dict[_Identity, str],
    directory: EntityDisplayDirectory,
) -> dict[_Identity, str]:
    if not refs:
        return {}
    resolved = directory.resolve_many(refs.values())
    return {identity: ref for identity, ref in refs.items() if ref in resolved}


def _copy_name(
    name: ResolvedEntityName | None,
    kind: _ValveKind,
    refs: dict[_Identity, str],
) -> ResolvedEntityName | None:
    if name is None:
        return None
    display_ref = (
        refs.get((kind, name.id)) if name.status == "found" and name.id > 0 else None
    )
    return name.model_copy(update={"display_ref": display_ref})


def _copy_guide_item(item: GuideItem, refs: dict[_Identity, str]) -> GuideItem:
    return item.model_copy(
        update={"resolved_name": _copy_name(item.resolved_name, "item", refs)}
    )


def _copy_item_observation(
    item: GuideItemObservation,
    refs: dict[_Identity, str],
) -> GuideItemObservation:
    return item.model_copy(
        update={"resolved_name": _copy_name(item.resolved_name, "item", refs)}
    )


def _copy_starting_option(
    option: StartingItemOption,
    refs: dict[_Identity, str],
) -> StartingItemOption:
    return option.model_copy(
        update={"items": [_copy_guide_item(item, refs) for item in option.items]}
    )


def _copy_skill_sequence(
    sequence: SkillSequenceOption,
    refs: dict[_Identity, str],
) -> SkillSequenceOption:
    return sequence.model_copy(
        update={
            "abilities": [
                _copy_name(ability, "ability", refs)
                for ability in sequence.abilities
            ]
        }
    )


def _copy_pub_guide(guide: PubGuide, refs: dict[_Identity, str]) -> PubGuide:
    return guide.model_copy(
        update={
            "starting_options": [
                _copy_starting_option(option, refs) for option in guide.starting_options
            ],
            "item_progression": [
                _copy_item_observation(item, refs) for item in guide.item_progression
            ],
            "situational_items": [
                _copy_item_observation(item, refs) for item in guide.situational_items
            ],
            "skill_sequences": [
                _copy_skill_sequence(sequence, refs)
                for sequence in guide.skill_sequences
            ],
        }
    )


def _copy_pro_item_event(
    event: ProItemEvent,
    refs: dict[_Identity, str],
) -> ProItemEvent:
    return event.model_copy(
        update={"resolved_name": _copy_name(event.resolved_name, "item", refs)}
    )


def _copy_pro_ability_event(
    event: ProAbilityEvent,
    refs: dict[_Identity, str],
) -> ProAbilityEvent:
    return event.model_copy(
        update={"resolved_name": _copy_name(event.resolved_name, "ability", refs)}
    )


def _copy_pro_example(
    example: ProMatchExample,
    refs: dict[_Identity, str],
) -> ProMatchExample:
    return example.model_copy(
        update={
            "item_timeline": [
                _copy_pro_item_event(event, refs) for event in example.item_timeline
            ],
            "ability_timeline": [
                _copy_pro_ability_event(event, refs)
                for event in example.ability_timeline
            ],
        }
    )


__all__ = ["enrich_hero_guide_display_refs"]
