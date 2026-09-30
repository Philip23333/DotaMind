from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.integrations.valve.catalog_repository import (
    CatalogLookupError,
    DotaCatalogRepository,
    load_default_catalog_repository,
)
from app.vnext.capabilities.hero.enrichment import enrich_hero_guide
from app.vnext.capabilities.hero.guide import (
    GuideItem,
    GuideItemObservation,
    GuideSourceMetadata,
    HeroGuideInput,
    HeroGuideResult,
    ProAbilityEvent,
    ProItemEvent,
    ProMatchExample,
    PubGuide,
    SkillSequenceOption,
    StartingItemOption,
)
from app.vnext.capabilities.hero.service import HeroGuideService
from app.vnext.catalog import EntityKind, EntityNameResolution, EntityNameResolver
from app.vnext.hero_guides.cache import GuideCacheEntry, GuideCacheSnapshot
from app.vnext.providers.d2pt.parsers import parse_pro_examples, parse_pub_builds

_NOW = datetime(2026, 9, 28, tzinfo=UTC)
_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "d2pt"
_UNKNOWN_ID = 2**31 - 1


class FakeGuideCache:
    def __init__(
        self,
        *,
        pub: GuideCacheSnapshot | None = None,
        pro: GuideCacheSnapshot | None = None,
    ) -> None:
        self.pub = GuideCacheEntry(snapshot=pub) if pub is not None else GuideCacheEntry()
        self.pro = GuideCacheEntry(snapshot=pro) if pro is not None else GuideCacheEntry()
        self.calls: list[str] = []

    async def get_pub(self, *, hero_id: int, position: int) -> GuideCacheEntry:
        self.calls.append(f"pub:{hero_id}:{position}")
        return self.pub

    async def get_pro(self, *, hero_id: int) -> GuideCacheEntry:
        self.calls.append(f"pro:{hero_id}")
        return self.pro


class RecordingResolver:
    def __init__(self, repository: DotaCatalogRepository) -> None:
        self._resolver = EntityNameResolver(repository)
        self.calls: list[tuple[EntityKind, list[int]]] = []

    def resolve_many(self, *, kind: EntityKind, ids: list[int]) -> EntityNameResolution:
        self.calls.append((kind, list(ids)))
        return self._resolver.resolve_many(kind=kind, ids=ids)


def _metadata(sample_type: str) -> GuideSourceMetadata:
    return GuideSourceMetadata(
        provider="d2pt",
        sample_type=sample_type,  # type: ignore[arg-type]
        availability="missing",
        stale=False,
    )


def _empty_result(hero_id: int, examples: list[ProMatchExample]) -> HeroGuideResult:
    return HeroGuideResult(
        hero_id=hero_id,
        position=1,
        section="all",
        pub_metadata=_metadata("pub"),
        pro_metadata=_metadata("pro"),
        pro_examples=examples,
    )


def _fixture_snapshot(name: str, hero_id: int, sample_type: str) -> GuideCacheSnapshot:
    raw = (_FIXTURE_DIR / name).read_bytes()
    rows = json.loads(raw)
    if sample_type == "pub":
        return GuideCacheSnapshot(
            sample_type="pub",
            hero_id=hero_id,
            position=1,
            retrieved_at=_NOW,
            content_type="application/json",
            raw_body=raw,
            source_rows=rows,
            pub_guides=parse_pub_builds(rows, hero_id=hero_id, position=1),
        )
    return GuideCacheSnapshot(
        sample_type="pro",
        hero_id=hero_id,
        position=None,
        retrieved_at=_NOW,
        content_type="application/json",
        raw_body=raw,
        source_rows=rows,
        pro_examples=parse_pro_examples(rows, hero_id=hero_id),
    )


def _check_name(
    repository: DotaCatalogRepository,
    kind: EntityKind,
    identifier: int,
    resolved: Any,
) -> None:
    record_lookup = {
        "hero": repository.get_hero,
        "item": repository.get_item,
        "ability": repository.get_ability,
    }[kind]
    try:
        record = record_lookup(identifier)
    except CatalogLookupError:
        assert resolved.id == identifier
        assert resolved.status == "unknown"
        assert resolved.name_en is None
        assert resolved.name_zh is None
    else:
        assert resolved.id == identifier
        assert resolved.status == "found"
        assert resolved.name_en == (record.name_en or None)
        assert resolved.name_zh == (record.name_zh or None)


def _complete_snapshots() -> tuple[GuideCacheSnapshot, GuideCacheSnapshot]:
    repository = load_default_catalog_repository()
    first_item, second_item = repository.list_items()[:2]
    first_ability, second_ability = repository.list_abilities()[:2]
    guide = PubGuide(
        starting_options=[
            StartingItemOption(
                items=[GuideItem(item_id=first_item.item_id, quantity=1, name="source item")],
                source_path="pub.starting",
            )
        ],
        item_progression=[
            GuideItemObservation(
                item_id=second_item.item_id,
                phase="mid",
                source_path="pub.progression",
            )
        ],
        situational_items=[
            GuideItemObservation(
                item_id=_UNKNOWN_ID,
                phase="unknown",
                name="provider supplied label",
                source_path="pub.situational",
            )
        ],
        skill_sequences=[
            SkillSequenceOption(
                ability_ids=[
                    first_ability.ability_id,
                    second_ability.ability_id,
                    first_ability.ability_id,
                ],
                source_path="pub.skills",
            )
        ],
    )
    example = ProMatchExample(
        source_match_id=101,
        hero_id=18,
        position=1,
        position_basis="build",
        item_timeline=[
            ProItemEvent(item_id=first_item.item_id),
            ProItemEvent(item_id=_UNKNOWN_ID),
        ],
        ability_timeline=[
            ProAbilityEvent(ability_id=0, source_fields={"ability_id": 0, "time": 20}),
            ProAbilityEvent(ability_id=first_ability.ability_id),
            ProAbilityEvent(ability_id=_UNKNOWN_ID),
        ],
        source_path="pro.match",
    )
    return (
        GuideCacheSnapshot(
            sample_type="pub",
            hero_id=18,
            position=1,
            retrieved_at=_NOW,
            content_type="application/json",
            raw_body=b"pub",
            source_rows=[],
            pub_guides=[guide],
        ),
        GuideCacheSnapshot(
            sample_type="pro",
            hero_id=18,
            position=None,
            retrieved_at=_NOW,
            content_type="application/json",
            raw_body=b"pro",
            source_rows=[],
            pro_examples=[example],
        ),
    )


def test_service_enriches_all_visible_entity_fields_with_batched_names() -> None:
    repository = load_default_catalog_repository()
    pub_snapshot, pro_snapshot = _complete_snapshots()
    cache_before = (
        pub_snapshot.model_dump(mode="json"),
        pro_snapshot.model_dump(mode="json"),
    )
    cache = FakeGuideCache(pub=pub_snapshot, pro=pro_snapshot)
    resolver = RecordingResolver(repository)

    result = asyncio.run(
        HeroGuideService(cache, lambda: resolver, clock=lambda: _NOW).get_guide(
            HeroGuideInput(hero_id=18, position=1)
        )
    )

    assert result.hero_name is not None
    _check_name(repository, "hero", 18, result.hero_name)
    assert result.catalog_version is not None
    assert result.catalog_version.model_dump() == resolver._resolver.resolve_many(
        kind="hero", ids=[18]
    ).catalog_version.model_dump()
    assert [kind for kind, _ids in resolver.calls] == ["hero", "item", "ability"]

    guide = result.pub_guides[0]
    start_item = guide.starting_options[0].items[0]
    _check_name(repository, "item", start_item.item_id, start_item.resolved_name)
    assert start_item.name == "source item"
    progression_item = guide.item_progression[0]
    _check_name(repository, "item", progression_item.item_id, progression_item.resolved_name)
    unknown_pub_item = guide.situational_items[0]
    _check_name(repository, "item", _UNKNOWN_ID, unknown_pub_item.resolved_name)
    assert unknown_pub_item.name == "provider supplied label"

    sequence = guide.skill_sequences[0]
    assert [name.id for name in sequence.abilities] == sequence.ability_ids
    assert len(sequence.abilities) == 3
    assert sequence.abilities[0] is not sequence.abilities[2]
    for ability_id, resolved in zip(sequence.ability_ids, sequence.abilities, strict=True):
        _check_name(repository, "ability", ability_id, resolved)

    example = result.pro_examples[0]
    assert [event.ability_id for event in example.ability_timeline] == [
        0,
        sequence.ability_ids[0],
        _UNKNOWN_ID,
    ]
    zero_event = example.ability_timeline[0]
    assert zero_event.resolved_name is not None
    assert zero_event.resolved_name.model_dump() == {
        "id": 0,
        "status": "unknown",
        "name_en": None,
        "name_zh": None,
    }
    assert zero_event.source_fields == {"ability_id": 0, "time": 20}
    assert example.ability_timeline[1].resolved_name is not sequence.abilities[0]
    for event in example.item_timeline:
        _check_name(repository, "item", event.item_id, event.resolved_name)
    for event in example.ability_timeline[1:]:
        _check_name(repository, "ability", event.ability_id, event.resolved_name)

    # Resolver outputs are copied per occurrence, and another query is unaffected.
    before_name = example.ability_timeline[1].resolved_name.name_en
    example.ability_timeline[1].resolved_name.name_en = "changed in response"
    assert sequence.abilities[0].name_en == before_name
    again = asyncio.run(
        HeroGuideService(
            cache, lambda: RecordingResolver(repository), clock=lambda: _NOW
        ).get_guide(
            HeroGuideInput(hero_id=18, position=1)
        )
    )
    assert again.pro_examples[0].ability_timeline[1].resolved_name.name_en == before_name
    assert pub_snapshot.model_dump(mode="json") == cache_before[0]
    assert pro_snapshot.model_dump(mode="json") == cache_before[1]
    assert cache.calls == ["pub:18:1", "pro:18", "pub:18:1", "pro:18"]
    assert not hasattr(cache, "publish")


@pytest.mark.parametrize(
    ("section", "expected_kinds"),
    [
        ("items", ["hero", "item"]),
        ("skills", ["hero", "ability"]),
        ("pro_examples", ["hero", "item", "ability"]),
    ],
)
def test_service_resolves_only_fields_visible_in_projected_section(
    section: str,
    expected_kinds: list[str],
) -> None:
    repository = load_default_catalog_repository()
    pub_snapshot, pro_snapshot = _complete_snapshots()
    resolver = RecordingResolver(repository)

    result = asyncio.run(
        HeroGuideService(
            FakeGuideCache(pub=pub_snapshot, pro=pro_snapshot), lambda: resolver
        )
        .get_guide(HeroGuideInput(hero_id=18, position=1, section=section))
    )

    assert [kind for kind, _ids in resolver.calls] == expected_kinds
    if section == "items":
        assert result.pro_examples == []
        assert result.pub_guides[0].skill_sequences == []
    elif section == "skills":
        assert result.pro_examples == []
        assert result.pub_guides[0].item_progression == []
        assert result.pub_guides[0].starting_options == []
    else:
        assert result.pub_guides == []
        assert result.pro_examples


def test_missing_cache_still_resolves_hero_and_keeps_sources_missing() -> None:
    repository = load_default_catalog_repository()
    resolver = RecordingResolver(repository)

    result = asyncio.run(
        HeroGuideService(FakeGuideCache(), lambda: resolver, clock=lambda: _NOW).get_guide(
            HeroGuideInput(hero_id=18, position=1)
        )
    )

    assert result.hero_name is not None
    _check_name(repository, "hero", 18, result.hero_name)
    assert result.catalog_version is not None
    assert result.pub_metadata.availability == "missing"
    assert result.pro_metadata.availability == "missing"
    assert resolver.calls == [("hero", [18])]


def test_real_sven_pub_and_pro_fixtures_enrich_names_from_local_catalog() -> None:
    repository = load_default_catalog_repository()
    cache = FakeGuideCache(
        pub=_fixture_snapshot("pub_sven_pos1.json", 18, "pub"),
        pro=_fixture_snapshot("pro_sven.json", 18, "pro"),
    )

    result = asyncio.run(
        HeroGuideService(
            cache, lambda: EntityNameResolver(repository), clock=lambda: _NOW
        ).get_guide(
            HeroGuideInput(hero_id=18, position=1)
        )
    )

    assert result.hero_name is not None
    assert result.catalog_version is not None
    assert result.catalog_version.source == "valve_dota2_datafeed"
    item_names = [
        item.resolved_name
        for guide in result.pub_guides
        for option in guide.starting_options
        for item in option.items
    ] + [
        item.resolved_name
        for guide in result.pub_guides
        for item in (*guide.item_progression, *guide.situational_items)
    ] + [
        event.resolved_name
        for example in result.pro_examples
        for event in example.item_timeline
    ]
    ability_names = [
        (ability_id, name)
        for guide in result.pub_guides
        for sequence in guide.skill_sequences
        for ability_id, name in zip(sequence.ability_ids, sequence.abilities, strict=True)
    ] + [
        (event.ability_id, event.resolved_name)
        for example in result.pro_examples
        for event in example.ability_timeline
    ]
    assert item_names
    assert ability_names
    for item in item_names:
        assert item is not None
        _check_name(repository, "item", item.id, item)
    for ability_id, name in ability_names:
        assert name is not None
        _check_name(repository, "ability", ability_id, name)


@pytest.mark.parametrize(
    ("name", "hero_id"),
    [
        ("pro_antimage.json", 1),
        ("pro_axe.json", 2),
        ("pro_crystal_maiden.json", 5),
    ],
)
def test_zero_skill_events_in_real_fixtures_remain_unknown(
    name: str,
    hero_id: int,
) -> None:
    raw = (_FIXTURE_DIR / name).read_bytes()
    examples = parse_pro_examples(json.loads(raw), hero_id=hero_id)
    zero_count = sum(
        event.ability_id == 0
        for example in examples
        for event in example.ability_timeline
    )
    result = enrich_hero_guide(
        _empty_result(hero_id, examples),
        EntityNameResolver(load_default_catalog_repository()),
    )

    resolved_zeros = [
        event.resolved_name
        for example in result.pro_examples
        for event in example.ability_timeline
        if event.ability_id == 0
    ]
    assert len(resolved_zeros) == zero_count
    assert zero_count > 0
    assert all(
        resolved is not None
        and resolved.id == 0
        and resolved.status == "unknown"
        and resolved.name_en is None
        and resolved.name_zh is None
        for resolved in resolved_zeros
    )


def test_resolver_errors_and_mixed_catalog_versions_propagate() -> None:
    pub_snapshot, _ = _complete_snapshots()
    repository = load_default_catalog_repository()

    class BrokenResolver:
        def resolve_many(self, *, kind: EntityKind, ids: list[int]) -> EntityNameResolution:
            raise OSError("catalog file unreadable")

    with pytest.raises(OSError, match="catalog file unreadable"):
        asyncio.run(
            HeroGuideService(
                FakeGuideCache(pub=pub_snapshot), lambda: BrokenResolver()
            ).get_guide(
                HeroGuideInput(hero_id=18, position=1)
            )
        )

    class MixedVersionResolver(RecordingResolver):
        def resolve_many(self, *, kind: EntityKind, ids: list[int]) -> EntityNameResolution:
            result = super().resolve_many(kind=kind, ids=ids)
            if kind == "item":
                result.catalog_version.patch = "different-version"
            return result

    with pytest.raises(ValueError, match="catalog version changed"):
        asyncio.run(
            HeroGuideService(
                FakeGuideCache(pub=pub_snapshot), lambda: MixedVersionResolver(repository)
            ).get_guide(HeroGuideInput(hero_id=18, position=1))
        )
