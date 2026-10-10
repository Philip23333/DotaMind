from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime

from app.integrations.valve.catalog_repository import (
    CatalogLookupError,
    DotaCatalogRepository,
    load_default_catalog_repository,
)
from app.vnext.artifacts import ArtifactLimits
from app.vnext.capabilities.catalog.display_enrichment import (
    enrich_catalog_lookup_result,
)
from app.vnext.capabilities.catalog.lookup import CatalogLookupInput
from app.vnext.capabilities.hero.display_enrichment import (
    enrich_hero_guide_display_refs,
)
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
    ResolvedEntityName,
    SkillSequenceOption,
    StartingItemOption,
)
from app.vnext.capabilities.hero.service import HeroGuideService
from app.vnext.catalog import EntityNameResolver
from app.vnext.composition import (
    VNextSettings,
    build_vnext_registry,
    build_vnext_services,
)
from app.vnext.entity_display import (
    DisplayEntity,
    EntityDisplayDirectory,
    parse_display_ref,
)
from app.vnext.hero_guides.cache import GuideCacheEntry, GuideCacheSnapshot
from app.vnext.llm.protocol import ToolCall
from app.vnext.providers.valve.catalog_lookup import ValveCatalogLookupAdapter

_NOW = datetime(2026, 10, 10, tzinfo=UTC)
_UNKNOWN_ID = 2**31 - 1


class FakeGuideCache:
    def __init__(self, pub: GuideCacheSnapshot, pro: GuideCacheSnapshot) -> None:
        self.pub = GuideCacheEntry(snapshot=pub)
        self.pro = GuideCacheEntry(snapshot=pro)

    async def get_pub(self, *, hero_id: int, position: int) -> GuideCacheEntry:
        assert (hero_id, position) == (18, 1)
        return self.pub

    async def get_pro(self, *, hero_id: int) -> GuideCacheEntry:
        assert hero_id == 18
        return self.pro


class CountingDirectory:
    def __init__(self, directory: EntityDisplayDirectory) -> None:
        self.directory = directory
        self.calls: list[list[str]] = []

    def resolve_many(self, refs: Iterable[str]):
        batch = list(refs)
        self.calls.append(batch)
        return self.directory.resolve_many(batch)


class PresentReferenceDirectory:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def resolve_many(self, refs: Iterable[str]) -> dict[str, DisplayEntity]:
        batch = list(dict.fromkeys(refs))
        self.calls.append(batch)
        resolved: dict[str, DisplayEntity] = {}
        for ref in batch:
            identity = parse_display_ref(ref)
            if identity is not None:
                resolved[ref] = DisplayEntity(
                    display_ref=ref,
                    kind=identity.kind,
                    label=ref,
                    image_url=None,
                )
        return resolved


def _named(
    repository: DotaCatalogRepository,
    kind: str,
    identifier: int,
    *,
    status: str | None = None,
) -> ResolvedEntityName:
    lookup = {
        "hero": repository.get_hero,
        "item": repository.get_item,
        "ability": repository.get_ability,
    }[kind]
    if status == "unknown" or identifier == 0:
        return ResolvedEntityName(
            id=identifier,
            status="unknown",
            name_en=None,
            name_zh=None,
        )
    try:
        record = lookup(identifier)
    except CatalogLookupError:
        return ResolvedEntityName(
            id=identifier,
            status="unknown",
            name_en=None,
            name_zh=None,
        )
    return ResolvedEntityName(
        id=identifier,
        status="found",
        name_en=record.name_en or None,
        name_zh=record.name_zh or None,
    )


def _guide_snapshots(
    repository: DotaCatalogRepository,
) -> tuple[GuideCacheSnapshot, GuideCacheSnapshot]:
    hero_id = 18
    item_id = repository.list_items()[0].item_id
    ability_id = repository.list_abilities()[0].ability_id
    pub = PubGuide(
        starting_options=[
            StartingItemOption(
                items=[
                    GuideItem(
                        item_id=item_id,
                        quantity=2,
                        name="source item name",
                        resolved_name=_named(repository, "item", item_id),
                    )
                ],
                source_path="pub.starting_options[0]",
            )
        ],
        item_progression=[
            GuideItemObservation(
                item_id=item_id,
                phase="mid",
                resolved_name=_named(repository, "item", item_id),
                source_path="pub.item_progression[0]",
            )
        ],
        situational_items=[
            GuideItemObservation(
                item_id=_UNKNOWN_ID,
                phase="unknown",
                resolved_name=_named(
                    repository, "item", _UNKNOWN_ID, status="unknown"
                ),
                source_path="pub.situational_items[0]",
            )
        ],
        skill_sequences=[
            SkillSequenceOption(
                ability_ids=[ability_id, ability_id],
                abilities=[
                    _named(repository, "ability", ability_id),
                    _named(repository, "ability", ability_id),
                ],
                source_path="pub.skill_sequences[0]",
            )
        ],
    )
    example = ProMatchExample(
        source_match_id=123,
        hero_id=hero_id,
        position=1,
        position_basis="build",
        item_timeline=[
            ProItemEvent(
                item_id=item_id,
                source_fields={"item_id": item_id, "time": 60},
                resolved_name=_named(repository, "item", item_id),
            )
        ],
        ability_timeline=[
            ProAbilityEvent(
                ability_id=0,
                source_fields={"ability_id": 0, "time": 20, "level": 2},
                resolved_name=_named(repository, "ability", 0),
            ),
            ProAbilityEvent(
                ability_id=ability_id,
                source_fields={"ability_id": ability_id, "time": 30},
                resolved_name=_named(repository, "ability", ability_id),
            ),
        ],
        source_path="pro.recent_matches[0]",
    )
    return (
        GuideCacheSnapshot(
            sample_type="pub",
            hero_id=hero_id,
            position=1,
            retrieved_at=_NOW,
            content_type="application/json",
            raw_body=b"{}",
            source_rows=[{}],
            pub_guides=[pub],
        ),
        GuideCacheSnapshot(
            sample_type="pro",
            hero_id=hero_id,
            position=None,
            retrieved_at=_NOW,
            content_type="application/json",
            raw_body=b"{}",
            source_rows=[{}],
            pro_examples=[example],
        ),
    )


def test_catalog_entries_receive_only_found_local_refs_without_data_dir() -> None:
    repository = load_default_catalog_repository()
    provider_calls = 0

    def repository_provider() -> DotaCatalogRepository:
        nonlocal provider_calls
        provider_calls += 1
        return repository

    directory = EntityDisplayDirectory(repository_provider)
    counter = CountingDirectory(directory)
    adapter = ValveCatalogLookupAdapter(repository_provider)
    result = asyncio.run(
        adapter.lookup(CatalogLookupInput(kind="hero", ids=[1, 1, _UNKNOWN_ID]))
    )

    enriched = enrich_catalog_lookup_result(result, counter)  # type: ignore[arg-type]

    assert [entry.display_ref for entry in enriched.entries] == [
        "display:valve:hero:1",
        "display:valve:hero:1",
        None,
    ]
    assert [entry.id for entry in enriched.entries] == [1, 1, _UNKNOWN_ID]
    assert [entry.status for entry in enriched.entries] == ["found", "found", "unknown"]
    assert enriched.catalog_version == result.catalog_version
    assert [entry.name_en for entry in enriched.entries] == [
        entry.name_en for entry in result.entries
    ]
    assert result.entries[0].display_ref is None
    assert counter.calls == [["display:valve:hero:1"]]
    assert provider_calls == 2  # One lookup snapshot and one display-resolution snapshot.

    resolved = directory.resolve_many(["display:valve:hero:1"])
    assert resolved["display:valve:hero:1"].image_url is None


def test_hero_guide_refs_cover_explicit_pub_and_pro_fields_without_mutation() -> None:
    repository = load_default_catalog_repository()
    pub_snapshot, pro_snapshot = _guide_snapshots(repository)
    cache_before = (
        pub_snapshot.model_dump(mode="json"),
        pro_snapshot.model_dump(mode="json"),
    )
    service = HeroGuideService(
        FakeGuideCache(pub_snapshot, pro_snapshot),
        lambda: EntityNameResolver(repository),
        clock=lambda: _NOW,
    )
    result = asyncio.run(service.get_guide(HeroGuideInput(hero_id=18, position=1)))
    counter = CountingDirectory(EntityDisplayDirectory(lambda: repository))

    enriched = enrich_hero_guide_display_refs(result, counter)  # type: ignore[arg-type]

    item_id = repository.list_items()[0].item_id
    ability_id = repository.list_abilities()[0].ability_id
    assert enriched.hero_name is not None
    assert enriched.hero_name.display_ref == "display:valve:hero:18"
    guide = enriched.pub_guides[0]
    assert guide.starting_options[0].items[0].resolved_name is not None
    assert guide.starting_options[0].items[0].resolved_name.display_ref == (
        f"display:valve:item:{item_id}"
    )
    assert guide.item_progression[0].resolved_name is not None
    assert guide.item_progression[0].resolved_name.display_ref == (
        f"display:valve:item:{item_id}"
    )
    assert guide.situational_items[0].resolved_name is not None
    assert guide.situational_items[0].resolved_name.status == "unknown"
    assert guide.situational_items[0].resolved_name.display_ref is None
    sequence = guide.skill_sequences[0]
    assert sequence.ability_ids == [ability_id, ability_id]
    assert [name.display_ref for name in sequence.abilities] == [
        f"display:valve:ability:{ability_id}",
        f"display:valve:ability:{ability_id}",
    ]
    example = enriched.pro_examples[0]
    assert example.item_timeline[0].resolved_name is not None
    assert example.item_timeline[0].resolved_name.display_ref == (
        f"display:valve:item:{item_id}"
    )
    assert example.ability_timeline[0].resolved_name is not None
    assert example.ability_timeline[0].resolved_name.id == 0
    assert example.ability_timeline[0].resolved_name.status == "unknown"
    assert example.ability_timeline[0].resolved_name.display_ref is None
    assert example.ability_timeline[1].resolved_name is not None
    assert example.ability_timeline[1].resolved_name.display_ref == (
        f"display:valve:ability:{ability_id}"
    )
    assert example.ability_timeline[0].source_fields == {
        "ability_id": 0,
        "time": 20,
        "level": 2,
    }
    assert counter.calls == [[
        "display:valve:hero:18",
        f"display:valve:item:{item_id}",
        f"display:valve:ability:{ability_id}",
    ]]
    assert all(
        entry.image_url is None
        for ref in counter.calls[0]
        for entry in [counter.directory.resolve_many([ref])[ref]]
    )
    assert result.hero_name is not None and result.hero_name.display_ref is None
    assert all(
        name is not None and name.display_ref is None
        for name in (
            result.pub_guides[0].starting_options[0].items[0].resolved_name,
            result.pub_guides[0].skill_sequences[0].abilities[0],
            result.pro_examples[0].item_timeline[0].resolved_name,
            result.pro_examples[0].ability_timeline[1].resolved_name,
        )
    )
    assert pub_snapshot.model_dump(mode="json") == cache_before[0]
    assert pro_snapshot.model_dump(mode="json") == cache_before[1]
    assert enriched.pub_guides[0].skill_sequences[0].abilities[0] is not (
        result.pub_guides[0].skill_sequences[0].abilities[0]
    )


def test_same_numeric_id_keeps_item_and_ability_references_distinct() -> None:
    same_id = 1
    found_name = ResolvedEntityName(
        id=same_id,
        status="found",
        name_en="same numeric identity",
        name_zh=None,
    )
    result = HeroGuideResult(
        hero_id=18,
        position=1,
        section="all",
        pub_metadata=GuideSourceMetadata(
            provider="d2pt",
            sample_type="pub",
            availability="available",
            stale=False,
        ),
        pro_metadata=GuideSourceMetadata(
            provider="d2pt",
            sample_type="pro",
            availability="empty",
            stale=False,
        ),
        pub_guides=[
            PubGuide(
                starting_options=[
                    StartingItemOption(
                        items=[
                            GuideItem(
                                item_id=same_id,
                                quantity=1,
                                name=None,
                                resolved_name=found_name,
                            )
                        ],
                        source_path="fixture.starting_items",
                    )
                ],
                skill_sequences=[
                    SkillSequenceOption(
                        ability_ids=[same_id],
                        abilities=[found_name],
                        source_path="fixture.abilities",
                    )
                ],
            )
        ],
    )
    directory = PresentReferenceDirectory()

    enriched = enrich_hero_guide_display_refs(  # type: ignore[arg-type]
        result, directory
    )

    item_ref = "display:valve:item:1"
    ability_ref = "display:valve:ability:1"
    assert directory.calls == [[item_ref, ability_ref]]
    assert (
        enriched.pub_guides[0].starting_options[0].items[0].resolved_name
        is not None
    )
    assert (
        enriched.pub_guides[0].starting_options[0].items[0].resolved_name.display_ref
        == item_ref
    )
    assert enriched.pub_guides[0].skill_sequences[0].abilities[0].display_ref == (
        ability_ref
    )


def test_section_projection_excludes_hidden_entities_from_display_lookup() -> None:
    repository = load_default_catalog_repository()
    pub_snapshot, pro_snapshot = _guide_snapshots(repository)
    service = HeroGuideService(
        FakeGuideCache(pub_snapshot, pro_snapshot),
        lambda: EntityNameResolver(repository),
        clock=lambda: _NOW,
    )
    projected = asyncio.run(
        service.get_guide(
            HeroGuideInput(hero_id=18, position=1, section="items")
        )
    )
    counter = CountingDirectory(EntityDisplayDirectory(lambda: repository))

    enriched = enrich_hero_guide_display_refs(projected, counter)  # type: ignore[arg-type]

    assert enriched.pro_examples == []
    assert enriched.pub_guides[0].skill_sequences == []
    assert counter.calls == [[
        "display:valve:hero:18",
        f"display:valve:item:{repository.list_items()[0].item_id}",
    ]]


def test_registry_keeps_catalog_and_guide_refs_through_artifact_read() -> None:
    repository = load_default_catalog_repository()
    pub_snapshot, pro_snapshot = _guide_snapshots(repository)
    settings = VNextSettings(
        artifact_limits=ArtifactLimits(
            inline_max_bytes=512,
            observation_max_bytes=8_192,
        )
    )
    services = build_vnext_services(
        settings,
        hero_guide_cache=FakeGuideCache(pub_snapshot, pro_snapshot),
        catalog_repository_provider=lambda: repository,
    )
    assert services.entity_display_directory is not None
    assert settings.data_dir is None
    assert services.entity_display_directory.resolve_many(
        ["display:pandascore:team:139340"]
    ) == {}
    registry = build_vnext_registry(services, settings=settings)

    async def execute():
        catalog = await registry.execute(
            ToolCall(
                id="catalog-lookup",
                name="catalog.lookup",
                arguments={"kind": "hero", "ids": [18]},
            )
        )
        guide = await registry.execute(
            ToolCall(
                id="hero-guide",
                name="hero.guide",
                arguments={"hero_id": 18, "position": 1, "section": "all"},
            )
        )
        assert guide.status == "ok"
        assert guide.content["externalized"] is True

        async def read(path: str, call_id: str):
            return await registry.execute(
                ToolCall(
                    id=call_id,
                    name="artifact.read",
                    arguments={
                        "ref": guide.content["artifact_ref"],
                        "mode": "read",
                        "path": path,
                    },
                )
            )

        return (
            catalog,
            await read("hero_name", "read-hero"),
            await read("pub_guides.0.starting_options.0.items.0.resolved_name", "read-item"),
            await read("pub_guides.0.skill_sequences.0.abilities.0", "read-ability"),
            await read("pro_examples.0.ability_timeline.1.resolved_name", "read-pro-ability"),
        )

    catalog, hero, item, ability, pro_ability = asyncio.run(execute())

    assert catalog.status == "ok"
    assert catalog.content["entries"][0]["display_ref"] == "display:valve:hero:18"
    assert hero.status == item.status == ability.status == pro_ability.status == "ok"
    assert hero.content["value"]["display_ref"] == "display:valve:hero:18"
    assert item.content["value"]["display_ref"].startswith("display:valve:item:")
    assert ability.content["value"]["display_ref"].startswith("display:valve:ability:")
    assert pro_ability.content["value"]["display_ref"].startswith(
        "display:valve:ability:"
    )
