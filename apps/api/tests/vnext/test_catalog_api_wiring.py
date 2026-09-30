from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.integrations.valve.catalog_repository import CATALOG_DIR, load_default_catalog_repository
from app.vnext.capabilities.catalog.lookup import CatalogLookupInput
from app.vnext.capabilities.hero.guide import HeroGuideInput
from app.vnext.capabilities.hero.service import HeroGuideService
from app.vnext.catalog import EntityNameResolver
from app.vnext.composition import VNextServices, VNextSettings, build_vnext_services
from app.vnext.data_updates.catalog_loader import (
    CatalogNotInitializedError,
    CatalogSnapshotLoader,
)
from app.vnext.data_updates.catalog_store import CatalogSnapshotStore, CatalogStoreError
from app.vnext.hero_guides.cache import GuideCacheEntry
from app.vnext.providers.valve.catalog_lookup import ValveCatalogLookupAdapter

_CATALOG_FILES = (
    "manifest.json",
    "dota2_heroes.json",
    "dota2_abilities.json",
    "dota2_items.json",
    "sync_audit.json",
)


class _EmptyGuideCache:
    async def get_pub(self, **_kwargs: Any) -> GuideCacheEntry:
        return GuideCacheEntry()

    async def get_pro(self, **_kwargs: Any) -> GuideCacheEntry:
        return GuideCacheEntry()


def _copy_catalog_source(destination: Path) -> Path:
    destination.mkdir(parents=True)
    for filename in _CATALOG_FILES:
        shutil.copyfile(CATALOG_DIR / filename, destination / filename)
    return destination


def _publish_catalog(data_dir: Path, source_name: str = "catalog-source") -> CatalogSnapshotStore:
    store = CatalogSnapshotStore(data_dir)
    store.publish_from_directory(_copy_catalog_source(data_dir.parent / source_name))
    return store


def _rewrite_sven(source_dir: Path, name: str) -> None:
    path = source_dir / "dota2_heroes.json"
    heroes = json.loads(path.read_text(encoding="utf-8"))
    next(hero for hero in heroes if hero["hero_id"] == 18)["name_en"] = name
    path.write_text(json.dumps(heroes, ensure_ascii=False), encoding="utf-8")


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_data_dir_environment_is_optional_but_must_be_nonempty_absolute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.vnext.composition as composition

    monkeypatch.setattr(composition, "dotenv_values", lambda _path: {})
    monkeypatch.delenv("DOTAMIND_DATA_DIR", raising=False)
    assert VNextSettings.from_env().data_dir is None

    for value in ("", "  ", "relative/catalog"):
        monkeypatch.setenv("DOTAMIND_DATA_DIR", value)
        with pytest.raises(ValueError, match="DOTAMIND_DATA_DIR"):
            VNextSettings.from_env()

    monkeypatch.setenv("DOTAMIND_DATA_DIR", f"  {tmp_path}  ")
    assert VNextSettings.from_env().data_dir == tmp_path


def test_composition_passes_one_lazy_repository_provider_to_catalog_consumers() -> None:
    repository = load_default_catalog_repository()
    calls: list[str] = []

    def provider():
        calls.append("repository")
        return repository

    services = build_vnext_services(
        VNextSettings(),
        hero_guide_cache=_EmptyGuideCache(),  # type: ignore[arg-type]
        catalog_repository_provider=provider,
    )

    catalog_adapter = services.catalog_lookup.__self__  # type: ignore[union-attr]
    guide_service = services.hero_guide.__self__  # type: ignore[union-attr]
    assert catalog_adapter._repository_provider is provider
    assert calls == []

    resolver = guide_service._resolver_factory()
    assert isinstance(resolver, EntityNameResolver)
    assert resolver._repository is repository
    assert calls == ["repository"]

    result = asyncio.run(
        services.catalog_lookup(CatalogLookupInput(kind="hero", ids=[18]))  # type: ignore[misc]
    )
    assert result.entries[0].name_en == repository.get_hero(18).name_en
    assert calls == ["repository", "repository"]


def test_concurrent_guide_queries_keep_the_catalog_snapshot_captured_before_cache_wait(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "persistent-data"
    store = _publish_catalog(data_dir)
    loader = CatalogSnapshotLoader(store)
    initial_name = load_default_catalog_repository().get_hero(18).name_en
    source_b = _copy_catalog_source(tmp_path / "source-b")
    _rewrite_sven(source_b, "Sven API Snapshot B")

    class GatedCache:
        def __init__(self) -> None:
            self.pub_started = [asyncio.Event(), asyncio.Event()]
            self.pub_release = [asyncio.Event(), asyncio.Event()]
            self.pub_calls = 0

        async def get_pub(self, **_kwargs: Any) -> GuideCacheEntry:
            call = self.pub_calls
            self.pub_calls += 1
            self.pub_started[call].set()
            await self.pub_release[call].wait()
            return GuideCacheEntry()

        async def get_pro(self, **_kwargs: Any) -> GuideCacheEntry:
            return GuideCacheEntry()

    async def exercise() -> None:
        await loader.start()
        try:
            cache = GatedCache()
            captured_revisions: list[str] = []
            resolvers: list[EntityNameResolver] = []

            def resolver_factory() -> EntityNameResolver:
                snapshot = loader.current()
                captured_revisions.append(snapshot.revision)
                resolver = EntityNameResolver(snapshot.repository)
                resolvers.append(resolver)
                return resolver

            service = HeroGuideService(cache, resolver_factory)
            first_task = asyncio.create_task(
                service.get_guide(HeroGuideInput(hero_id=18, position=1))
            )
            await cache.pub_started[0].wait()
            first = loader.current()

            store.publish_from_directory(source_b)
            assert await loader.refresh_once()
            second = loader.current()
            assert first.revision != second.revision
            assert first.repository.snapshot_metadata()["patch"] == (
                second.repository.snapshot_metadata()["patch"]
            )

            lookup_provider_calls = 0

            def repository_provider():
                nonlocal lookup_provider_calls
                lookup_provider_calls += 1
                return loader.current().repository

            lookup = await ValveCatalogLookupAdapter(repository_provider).lookup(
                CatalogLookupInput(kind="hero", ids=[18])
            )
            assert lookup.entries[0].name_en == "Sven API Snapshot B"
            assert lookup_provider_calls == 1

            second_task = asyncio.create_task(
                service.get_guide(HeroGuideInput(hero_id=18, position=1))
            )
            await cache.pub_started[1].wait()
            cache.pub_release[0].set()
            cache.pub_release[1].set()
            first_result, second_result = await asyncio.gather(first_task, second_task)

            assert first_result.hero_name is not None
            assert second_result.hero_name is not None
            assert first_result.hero_name.name_en == first.repository.get_hero(18).name_en
            assert first_result.hero_name.name_en != second_result.hero_name.name_en
            assert second_result.hero_name.name_en == second.repository.get_hero(18).name_en
            assert first_result.hero_name.name_en == initial_name
            assert second_result.hero_name.name_en == "Sven API Snapshot B"
            assert captured_revisions == [first.revision, second.revision]
            assert len(resolvers) == 2 and resolvers[0] is not resolvers[1]

            pointer = store._current_pointer
            previous_pointer = pointer.read_bytes()
            pointer.write_text(
                json.dumps({"schema_version": 1, "revision": "f" * 32}),
                encoding="utf-8",
            )
            with pytest.raises(CatalogStoreError) as raised:
                await loader.refresh_once()
            assert raised.value.reason == "invalid_snapshot"
            after_failure = await ValveCatalogLookupAdapter(repository_provider).lookup(
                CatalogLookupInput(kind="hero", ids=[18])
            )
            assert after_failure.entries[0].name_en == "Sven API Snapshot B"
            pointer.write_bytes(previous_pointer)
        finally:
            await loader.stop()

    asyncio.run(exercise())


def _patch_lifespan_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    data_dir: Path,
    events: list[str],
    captures: dict[str, Any],
    initialize=None,
) -> None:
    import app.application.plan_service as plan_service_module
    from app import main

    class TrackingLoader(CatalogSnapshotLoader):
        async def start(self) -> None:
            await super().start()
            events.append("loader_started")

        async def stop(self) -> None:
            await super().stop()
            events.append("loader_stopped")

    class SessionStore:
        async def aclose(self) -> None:
            return None

    async def no_op(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(main, "CatalogSnapshotLoader", TrackingLoader)
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(redis_url=None, database_url="postgresql://fixture.invalid/db"),
    )
    monkeypatch.setattr(
        main.VNextSettings,
        "from_env",
        classmethod(lambda _cls: VNextSettings(data_dir=data_dir)),
    )
    monkeypatch.setattr(
        main,
        "create_database_resources",
        lambda _url: SimpleNamespace(engine=object(), session_factory=object()),
    )
    monkeypatch.setattr(main, "ping_database", no_op)
    monkeypatch.setattr(main, "close_database", no_op)
    monkeypatch.setattr(main, "build_session_store", lambda *_args: SessionStore())
    monkeypatch.setattr(main, "PostgresChatRepository", lambda _factory: object())
    monkeypatch.setattr(main, "PostgresChatRunRepository", lambda _factory: object())
    monkeypatch.setattr(
        main,
        "get_policy",
        lambda: SimpleNamespace(
            conversation=SimpleNamespace(
                recent_dialogue_max_chars=100,
                history_lookup_max_turns=2,
                history_lookup_max_chars=100,
            )
        ),
    )
    monkeypatch.setattr(
        plan_service_module,
        "PlanService",
        lambda: SimpleNamespace(
            runner=object(), _build_turn=object(), _public_response=object()
        ),
    )

    def build_services(
        _settings: VNextSettings,
        *,
        hero_guide_cache=None,
        catalog_repository_provider=None,
    ) -> VNextServices:
        assert events[-1:] == ["loader_started"]
        captures["composition_provider"] = catalog_repository_provider
        return VNextServices()

    def chat_service(*args: Any, **_kwargs: Any) -> object:
        captures["presentation_enricher"] = args[3]
        return object()

    monkeypatch.setattr(main, "build_vnext_services", build_services)
    monkeypatch.setattr(main, "initialize_vnext_services", initialize or no_op)
    monkeypatch.setattr(main, "build_vnext_runtime", lambda **_kwargs: object())
    monkeypatch.setattr(main, "VNextChatService", chat_service)


def test_api_lifespan_starts_loader_before_consumers_and_stops_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    data_dir = tmp_path / "persistent-data"
    _publish_catalog(data_dir)
    before = _tree_bytes(data_dir)
    events: list[str] = []
    captures: dict[str, Any] = {}
    _patch_lifespan_dependencies(
        monkeypatch,
        data_dir=data_dir,
        events=events,
        captures=captures,
    )

    original_app_state = main.app.state._state.copy()
    try:
        async def exercise() -> None:
            async with main.lifespan(main.app):
                provider = captures["composition_provider"]
                enricher = captures["presentation_enricher"]
                assert callable(provider)
                assert enricher._catalog_repository_provider is provider
                assert provider().get_hero(18).hero_id == 18
                assert events == ["loader_started"]

        asyncio.run(exercise())
    finally:
        main.app.state._state.clear()
        main.app.state._state.update(original_app_state)

    assert events == ["loader_started", "loader_stopped"]
    assert _tree_bytes(data_dir) == before


@pytest.mark.parametrize("failure", ["initialization", "cancellation"])
def test_api_lifespan_stops_loader_after_later_startup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    from app import main

    data_dir = tmp_path / "persistent-data"
    _publish_catalog(data_dir)
    events: list[str] = []
    captures: dict[str, Any] = {}
    entered_initialization = asyncio.Event()

    async def initialize(*_args: Any, **_kwargs: Any) -> None:
        entered_initialization.set()
        if failure == "initialization":
            raise RuntimeError("injected service initialization failure")
        await asyncio.Event().wait()

    _patch_lifespan_dependencies(
        monkeypatch,
        data_dir=data_dir,
        events=events,
        captures=captures,
        initialize=initialize,
    )
    original_app_state = main.app.state._state.copy()

    async def exercise() -> None:
        if failure == "initialization":
            with pytest.raises(RuntimeError, match="injected service initialization failure"):
                async with main.lifespan(main.app):
                    pytest.fail("startup failure should happen before yield")
            return

        async def enter() -> None:
            async with main.lifespan(main.app):
                pytest.fail("startup cancellation should happen before yield")

        task = asyncio.create_task(enter())
        await entered_initialization.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(exercise())
    finally:
        main.app.state._state.clear()
        main.app.state._state.update(original_app_state)

    assert events == ["loader_started", "loader_stopped"]


@pytest.mark.parametrize("pointer_state", ["missing", "corrupt"])
def test_configured_missing_or_corrupt_snapshot_fails_startup_without_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pointer_state: str,
) -> None:
    from app import main

    data_dir = tmp_path / "persistent-data"
    if pointer_state == "corrupt":
        pointer = data_dir / "catalog" / "current.json"
        pointer.parent.mkdir(parents=True)
        pointer.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(main, "settings", SimpleNamespace(redis_url=None))
    monkeypatch.setattr(
        main.VNextSettings,
        "from_env",
        classmethod(lambda _cls: VNextSettings(data_dir=data_dir)),
    )
    original_app_state = main.app.state._state.copy()

    try:
        if pointer_state == "missing":
            with pytest.raises(CatalogNotInitializedError):
                asyncio.run(main.lifespan(main.app).__aenter__())
            assert not data_dir.exists()
        else:
            with pytest.raises(CatalogStoreError) as raised:
                asyncio.run(main.lifespan(main.app).__aenter__())
            assert raised.value.reason == "invalid_pointer"
            assert (data_dir / "catalog" / "current.json").read_text(
                encoding="utf-8"
            ) == "{not-json"
    finally:
        main.app.state._state.clear()
        main.app.state._state.update(original_app_state)
