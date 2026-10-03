from __future__ import annotations

import asyncio
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.integrations.valve.catalog_repository import CATALOG_DIR, load_default_catalog_repository
from app.vnext.artifacts import (
    ArtifactBackedToolResultProcessor,
    ArtifactGrepper,
    ArtifactReader,
    SessionArtifactStore,
    ToolResponseExternalizer,
)
from app.vnext.capabilities.hero.guide import (
    GuideItem,
    HeroGuideInput,
    PubGuide,
    SkillSequenceOption,
    StartingItemOption,
)
from app.vnext.capabilities.hero.service import HeroGuideQueryError, HeroGuideService
from app.vnext.catalog import EntityNameResolver
from app.vnext.composition import (
    VNextSettings,
    build_vnext_registry,
    build_vnext_services,
)
from app.vnext.data_updates.catalog_loader import CatalogSnapshotLoader
from app.vnext.data_updates.catalog_store import CatalogSnapshotStore
from app.vnext.hero_guides.cache import (
    GuideCacheEntry,
    GuideCacheSnapshot,
)
from app.vnext.hero_guides.file_cache import FileHeroGuideCache
from app.vnext.llm.protocol import ToolCall
from app.vnext.providers.d2pt.parsers import parse_pro_examples, parse_pub_builds
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.hero.guide import register_hero_guide_tool
from app.vnext.tools.registry import ToolRegistry

_NOW = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)
_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "d2pt"
_CATALOG_FILES = (
    "manifest.json",
    "dota2_heroes.json",
    "dota2_abilities.json",
    "dota2_items.json",
    "sync_audit.json",
)


def _run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def _fixture_snapshot(
    filename: str,
    *,
    sample_type: str,
    position: int | None,
) -> GuideCacheSnapshot:
    raw_body = (_FIXTURE_DIR / filename).read_bytes()
    source_rows = json.loads(raw_body)
    if sample_type == "pub":
        pub_guides = parse_pub_builds(source_rows, hero_id=18, position=position)
        pro_examples = []
    else:
        pub_guides = []
        pro_examples = parse_pro_examples(source_rows, hero_id=18)
    return GuideCacheSnapshot(
        sample_type=sample_type,
        hero_id=18,
        position=position,
        retrieved_at=_NOW,
        content_type="application/json",
        raw_body=raw_body,
        source_rows=source_rows,
        pub_guides=pub_guides,
        pro_examples=pro_examples,
    )


class TrackingFileCache(FileHeroGuideCache):
    def __init__(self, data_root: Path) -> None:
        super().__init__(data_root)
        self.reads: list[str] = []
        self.writes: list[str] = []

    async def get_pub(self, *, hero_id: int, position: int) -> GuideCacheEntry:
        self.reads.append(f"pub:{hero_id}:{position}")
        return await super().get_pub(hero_id=hero_id, position=position)

    async def get_pro(self, *, hero_id: int) -> GuideCacheEntry:
        self.reads.append(f"pro:{hero_id}")
        return await super().get_pro(hero_id=hero_id)

    async def publish(self, snapshot: GuideCacheSnapshot, *, attempted_at: datetime) -> None:
        self.writes.append("publish")
        await super().publish(snapshot, attempted_at=attempted_at)

    async def record_failure(self, **kwargs: Any) -> None:
        self.writes.append("record_failure")
        await super().record_failure(**kwargs)

    async def import_entry(self, **kwargs: Any) -> bool:
        self.writes.append("import_entry")
        return await super().import_entry(**kwargs)


def _guide_service(cache: FileHeroGuideCache) -> HeroGuideService:
    repository = load_default_catalog_repository()
    return HeroGuideService(
        cache,
        lambda: EntityNameResolver(repository),
        clock=lambda: _NOW,
    )


def _tool_registry(service_lookup) -> tuple[ToolRegistry, SessionArtifactStore]:
    artifact_store = SessionArtifactStore()
    registry = ToolRegistry(
        result_processor=ArtifactBackedToolResultProcessor(
            ToolResponseExternalizer(artifact_store)
        )
    )
    register_artifact_tools(
        registry,
        ArtifactReader(artifact_store),
        ArtifactGrepper(artifact_store),
    )
    register_hero_guide_tool(registry, service_lookup)
    return registry, artifact_store


def _tree(root: Path) -> tuple[dict[str, bytes], dict[str, int]]:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    return (
        {path.relative_to(root).as_posix(): path.read_bytes() for path in files},
        {path.relative_to(root).as_posix(): path.stat().st_mtime_ns for path in files},
    )


def test_guide_api_uses_files_only_when_data_dir_is_configured(tmp_path: Path) -> None:
    from app.main import _hero_guide_cache_for_data_dir

    root = tmp_path / "data"
    file_cache = FileHeroGuideCache(root)
    file_snapshot = _fixture_snapshot("pub_sven_pos1.json", sample_type="pub", position=1)
    file_snapshot = file_snapshot.model_copy(
        update={"pub_guides": [PubGuide(build_id=888, statistics={"source": "file"})]}
    )
    _run(file_cache.publish(file_snapshot, attempted_at=_NOW))

    chosen = _hero_guide_cache_for_data_dir(root)
    assert isinstance(chosen, FileHeroGuideCache)
    services = build_vnext_services(
        VNextSettings(data_dir=root),
        hero_guide_cache=chosen,
    )
    assert services.hero_guide is not None
    result = _run(services.hero_guide(HeroGuideInput(hero_id=18, position=1)))
    assert [guide.build_id for guide in result.pub_guides] == [888]
    assert result.pub_guides[0].statistics["source"] == "file"
    assert chosen._guides_directory == root / "guides"

    assert isinstance(_hero_guide_cache_for_data_dir(root), FileHeroGuideCache)
    file_only_settings = VNextSettings(data_dir=root)
    file_only_services = build_vnext_services(
        file_only_settings,
        hero_guide_cache=_hero_guide_cache_for_data_dir(root),
    )
    file_only_names = {
        tool.name
        for tool in build_vnext_registry(
            file_only_services,
            settings=file_only_settings,
        ).schemas()
    }
    assert "hero.guide" in file_only_names
    assert _hero_guide_cache_for_data_dir(None) is None
    assert build_vnext_services(VNextSettings()).hero_guide is None


def test_file_guide_service_tool_and_artifact_read_keep_only_projected_data(
    tmp_path: Path,
) -> None:
    cache = TrackingFileCache(tmp_path)
    repository = load_default_catalog_repository()
    item_id = repository.list_items()[0].item_id
    ability_id = repository.list_abilities()[0].ability_id
    pub = _fixture_snapshot("pub_sven_pos1.json", sample_type="pub", position=1)
    pub_guides = list(pub.pub_guides)
    pub_guides.append(
        PubGuide(
            build_id=9001,
            statistics={"large_test_value": "z" * 15_000},
            starting_options=[
                StartingItemOption(
                    items=[GuideItem(item_id=item_id, quantity=1, name="source")],
                    source_path="$.starting_items_new[0]",
                )
            ],
            skill_sequences=[
                SkillSequenceOption(
                    ability_ids=[ability_id],
                    source_path="$.abilities_new[0]",
                )
            ],
        )
    )
    pub = pub.model_copy(
        update={
            "pub_guides": pub_guides,
            "source_rows": [
                {**row, "private_source_marker": "SOURCE_ROWS_PRIVATE"}
                for row in pub.source_rows
            ],
        }
    )
    pro = _fixture_snapshot("pro_sven.json", sample_type="pro", position=None)

    async def seed() -> None:
        await cache.publish(pub, attempted_at=_NOW)
        await cache.publish(pro, attempted_at=_NOW)

    _run(seed())
    cache.writes.clear()
    before_bytes, before_mtimes = _tree(tmp_path)

    services = build_vnext_services(
        VNextSettings(data_dir=tmp_path),
        hero_guide_cache=cache,
    )
    assert services.hero_guide is not None
    registry, artifact_store = _tool_registry(services.hero_guide)
    result = _run(
        registry.execute(
            ToolCall(
                id="file-guide",
                name="hero.guide",
                arguments={"hero_id": 18, "position": 1},
            )
        )
    )

    assert result.status == "ok"
    assert result.content["externalized"] is True
    reference = result.content["artifact_ref"]
    stored = _run(artifact_store.get(reference))
    assert stored["hero_name"]["name_en"] == repository.get_hero(18).name_en
    assert stored["catalog_version"]["patch"] == repository.snapshot_metadata()["patch"]
    assert stored["pub_metadata"]["availability"] == "available"
    assert stored["pro_metadata"]["availability"] in {"available", "empty"}
    assert stored["pub_guides_total"] == len(pub.pub_guides)
    assert "raw_body" not in str(stored)
    assert "source_rows" not in str(stored)
    assert "SOURCE_ROWS_PRIVATE" not in str(stored)
    assert pub.raw_body.decode("utf-8") not in str(stored)

    read_result = _run(
        registry.execute(
            ToolCall(
                id="read-file-guide-artifact",
                name="artifact.read",
                arguments={
                    "ref": reference,
                    "mode": "read",
                    "path": "pub_guides",
                    "offset": len(pub.pub_guides) - 1,
                    "limit": 1,
                },
            )
        )
    )
    assert read_result.status == "ok"
    resolved_guide = read_result.content["value"][0]
    assert resolved_guide["build_id"] == 9001
    assert resolved_guide["starting_options"][0]["items"][0]["resolved_name"]["name_en"] == (
        repository.get_item(item_id).name_en
    )
    assert resolved_guide["skill_sequences"][0]["abilities"][0]["name_en"] == (
        repository.get_ability(ability_id).name_en or None
    )
    assert "RAW_SOURCE_BYTES_PRIVATE" not in read_result.model_dump_json()
    assert "SOURCE_ROWS_PRIVATE" not in read_result.model_dump_json()

    skills_result = _run(
        services.hero_guide(HeroGuideInput(hero_id=18, position=1, section="skills"))
    )
    assert skills_result.section == "skills"
    assert skills_result.pub_guides_total == len(pub.pub_guides)
    assert all(not guide.starting_options for guide in skills_result.pub_guides)
    assert all(guide.skill_sequences for guide in skills_result.pub_guides)
    assert cache.reads == ["pub:18:1", "pro:18", "pub:18:1", "pro:18"]
    assert cache.writes == []
    assert _tree(tmp_path) == (before_bytes, before_mtimes)


def test_file_partition_updates_are_visible_next_query_and_preserve_failure_state(
    tmp_path: Path,
) -> None:
    cache = TrackingFileCache(tmp_path)
    service = _guide_service(cache)
    original = _fixture_snapshot("pub_sven_pos1.json", sample_type="pub", position=1)
    first = original.model_copy(update={"pub_guides": [PubGuide(build_id=11)]})
    _run(cache.publish(first, attempted_at=_NOW))
    cache.writes.clear()

    initial = _run(service.get_guide(HeroGuideInput(hero_id=18, position=1)))
    assert [guide.build_id for guide in initial.pub_guides] == [11]

    second = original.model_copy(update={"pub_guides": [PubGuide(build_id=22)]})
    _run(cache.publish(second, attempted_at=_NOW))
    cache.writes.clear()
    updated = _run(service.get_guide(HeroGuideInput(hero_id=18, position=1)))
    assert [guide.build_id for guide in updated.pub_guides] == [22]

    _run(
        cache.record_failure(
            sample_type="pub",
            hero_id=18,
            position=1,
            attempted_at=_NOW,
            error_code="timeout",
        )
    )
    cache.writes.clear()
    retained = _run(service.get_guide(HeroGuideInput(hero_id=18, position=1)))
    assert [guide.build_id for guide in retained.pub_guides] == [22]
    assert retained.pub_metadata.availability == "available"
    assert retained.pub_metadata.stale is True
    assert retained.pub_metadata.last_error == "timeout"
    assert cache.writes == []


def test_file_missing_empty_and_corrupt_partitions_keep_existing_query_semantics(
    tmp_path: Path,
) -> None:
    cache = TrackingFileCache(tmp_path)
    service = _guide_service(cache)
    empty_snapshot = GuideCacheSnapshot(
        sample_type="pub",
        hero_id=18,
        position=2,
        retrieved_at=_NOW,
        content_type="application/json",
        raw_body=b"[]",
        source_rows=[],
    )
    _run(cache.publish(empty_snapshot, attempted_at=_NOW))
    cache.writes.clear()

    empty = _run(service.get_guide(HeroGuideInput(hero_id=18, position=2)))
    missing = _run(service.get_guide(HeroGuideInput(hero_id=1, position=1)))
    assert empty.pub_metadata.availability == "empty"
    assert empty.pub_guides_total == 0
    assert missing.pub_metadata.availability == "missing"
    assert missing.pub_guides_total is None
    assert missing.pro_metadata.availability == "missing"

    pub_path = tmp_path / "guides" / "pub" / "18" / "2.json"
    pub_path.write_bytes(b"not-json")
    pro_path = tmp_path / "guides" / "pro" / "18.json"
    _run(
        cache.publish(
            _fixture_snapshot("pro_sven.json", sample_type="pro", position=None),
            attempted_at=_NOW,
        )
    )
    cache.writes.clear()
    single_failure = _run(service.get_guide(HeroGuideInput(hero_id=18, position=2)))
    assert single_failure.pub_metadata.last_error == "cache_invalid_data"
    assert single_failure.pub_metadata.availability == "missing"
    assert single_failure.pro_metadata.availability in {"available", "empty"}

    pro_path.write_bytes(b"also-not-json")
    with pytest.raises(HeroGuideQueryError) as raised:
        _run(service.get_guide(HeroGuideInput(hero_id=18, position=2)))
    assert raised.value.pub_error == "cache_invalid_data"
    assert raised.value.pro_error == "cache_invalid_data"
    assert cache.writes == []


def _copy_catalog_source(destination: Path) -> Path:
    destination.mkdir(parents=True)
    for filename in _CATALOG_FILES:
        shutil.copyfile(CATALOG_DIR / filename, destination / filename)
    return destination


def _rename_sven(source: Path, value: str) -> None:
    path = source / "dota2_heroes.json"
    heroes = json.loads(path.read_text(encoding="utf-8"))
    next(hero for hero in heroes if hero["hero_id"] == 18)["name_en"] = value
    path.write_text(json.dumps(heroes, ensure_ascii=False), encoding="utf-8")


def test_guide_query_keeps_catalog_snapshot_captured_before_file_read_wait(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "shared-data"
    source_a = _copy_catalog_source(tmp_path / "catalog-a")
    store = CatalogSnapshotStore(data_root)
    store.publish_from_directory(source_a)
    loader = CatalogSnapshotLoader(store)
    cache = TrackingFileCache(data_root)
    _run(
        cache.publish(
            _fixture_snapshot("pub_sven_pos1.json", sample_type="pub", position=1),
            attempted_at=_NOW,
        )
    )
    cache.writes.clear()
    original_name = loader_name = load_default_catalog_repository().get_hero(18).name_en
    started = asyncio.Event()
    release = asyncio.Event()

    class GatedCache(TrackingFileCache):
        async def get_pub(self, *, hero_id: int, position: int) -> GuideCacheEntry:
            self.reads.append(f"pub:{hero_id}:{position}")
            started.set()
            await release.wait()
            return await FileHeroGuideCache.get_pub(
                self,
                hero_id=hero_id,
                position=position,
            )

    gated_cache = GatedCache(data_root)
    service = HeroGuideService(
        gated_cache,
        lambda: EntityNameResolver(loader.current().repository),
        clock=lambda: _NOW,
    )
    assert original_name == loader_name

    async def exercise() -> None:
        await loader.start()
        try:
            pending = asyncio.create_task(
                service.get_guide(HeroGuideInput(hero_id=18, position=1))
            )
            await started.wait()
            source_b = _copy_catalog_source(tmp_path / "catalog-b")
            _rename_sven(source_b, "Sven File Snapshot B")
            store.publish_from_directory(source_b)
            assert await loader.refresh_once()
            release.set()
            captured_result = await pending
            assert captured_result.hero_name is not None
            assert captured_result.hero_name.name_en == original_name

            next_result = await service.get_guide(HeroGuideInput(hero_id=18, position=1))
            assert next_result.hero_name is not None
            assert next_result.hero_name.name_en == "Sven File Snapshot B"
            assert gated_cache.writes == []
        finally:
            release.set()
            await loader.stop()

    _run(exercise())
