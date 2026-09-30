from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from app.vnext.composition import VNextSettings, build_vnext_registry, build_vnext_services
from app.vnext.hero_guides.cache import GuideCacheEntry
from app.vnext.llm.protocol import ToolCall


class IdleCache:
    def __init__(self) -> None:
        self.reads: list[str] = []

    async def get_pub(self, **_kwargs: Any) -> GuideCacheEntry:
        self.reads.append("pub")
        return GuideCacheEntry()

    async def get_pro(self, **_kwargs: Any) -> GuideCacheEntry:
        self.reads.append("pro")
        return GuideCacheEntry()


def test_hero_guide_is_registered_only_when_cache_is_injected() -> None:
    settings = VNextSettings()
    without_cache = build_vnext_services(settings)
    missing_registry = build_vnext_registry(without_cache, settings=settings)
    assert without_cache.hero_guide is None
    assert "hero.guide" not in {tool.name for tool in missing_registry.schemas()}

    cache = IdleCache()
    with_cache = build_vnext_services(settings, hero_guide_cache=cache)  # type: ignore[arg-type]
    service = with_cache.hero_guide.__self__  # type: ignore[union-attr]
    assert service._cache is cache
    repository_provider = with_cache.catalog_lookup.__self__._repository_provider  # type: ignore[union-attr]
    catalog_repository = repository_provider()
    assert service._resolver_factory()._repository is catalog_repository
    assert cache.reads == []

    catalog_lookup_calls: list[object] = []

    async def unexpected_catalog_lookup(query: object) -> object:
        catalog_lookup_calls.append(query)
        raise AssertionError("hero.guide must use the injected resolver directly")

    with_cache.catalog_lookup = unexpected_catalog_lookup  # type: ignore[assignment]
    registry = build_vnext_registry(with_cache, settings=settings)
    names = [tool.name for tool in registry.schemas()]
    assert callable(with_cache.hero_guide)
    assert names.count("hero.guide") == 1
    assert "catalog.lookup" in names

    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="guide-with-local-names",
                name="hero.guide",
                arguments={"hero_id": 18, "position": 1},
            )
        )
    )

    assert result.status == "ok"
    assert result.content["hero_name"]["id"] == 18
    assert catalog_lookup_calls == []
    assert cache.reads == ["pub", "pro"]


def test_application_lifespan_wraps_its_existing_redis_client_for_hero_guides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.application.plan_service as plan_service_module
    from app import main

    class FakeRedis:
        def __init__(self) -> None:
            self.ping_calls = 0
            self.close_calls = 0
            self.hgetall_calls: list[str] = []

        async def ping(self) -> bool:
            self.ping_calls += 1
            return True

        async def aclose(self) -> None:
            self.close_calls += 1

        async def hgetall(self, key: str) -> dict[str, str]:
            self.hgetall_calls.append(key)
            return {}

    class FakeStore:
        async def aclose(self) -> None:
            return None

    class FakeEventBus:
        def __init__(self, *, redis_url: str) -> None:
            self.redis_url = redis_url

        async def ping(self) -> None:
            return None

        async def aclose(self) -> None:
            return None

        def subscribe_cancellations(self) -> object:
            return object()

    class FakeRunManager:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def start(self) -> None:
            return None

        async def shutdown(self) -> None:
            return None

    class FakeSweeper:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    redis = FakeRedis()
    redis_urls: list[str] = []

    def from_url(url: str, **_kwargs: Any) -> FakeRedis:
        redis_urls.append(url)
        return redis

    monkeypatch.setattr("redis.asyncio.from_url", from_url)
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            redis_url="redis://fixture.invalid/0",
            database_url="postgresql://fixture.invalid/db",
            max_concurrent_chat_runs=1,
            run_heartbeat_seconds=5,
            run_stale_seconds=60,
            run_sweeper_interval_seconds=15,
        ),
    )
    monkeypatch.setattr(main.VNextSettings, "from_env", classmethod(lambda _cls: VNextSettings()))
    monkeypatch.setattr(main, "create_database_resources", lambda _url: SimpleNamespace(
        engine=object(), session_factory=object()
    ))

    async def no_op(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(main, "ping_database", no_op)
    monkeypatch.setattr(main, "close_database", no_op)
    monkeypatch.setattr(main, "build_session_store", lambda *_args: FakeStore())
    monkeypatch.setattr(main, "PostgresChatRepository", lambda _factory: object())
    monkeypatch.setattr(main, "PostgresChatRunRepository", lambda _factory: object())
    monkeypatch.setattr(main, "RedisTraceStore", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(main, "RedisRunEventBus", FakeEventBus)
    monkeypatch.setattr(main, "BackgroundRunManager", FakeRunManager)
    monkeypatch.setattr(main, "RunStaleSweeper", FakeSweeper)
    monkeypatch.setattr(main, "ChatRunExecutor", lambda **_kwargs: object())
    monkeypatch.setattr(main, "ChatRunRuntime", lambda **_kwargs: object())
    monkeypatch.setattr(main, "VNextChatService", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(main, "ConversationMemoryService", lambda **_kwargs: object())
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
    captured_caches: list[object] = []
    original_builder = main.build_vnext_services

    def capture_builder(
        settings: VNextSettings,
        *,
        hero_guide_cache=None,
        catalog_repository_provider=None,
    ):
        captured_caches.append(hero_guide_cache)
        return original_builder(
            settings,
            hero_guide_cache=hero_guide_cache,
            catalog_repository_provider=catalog_repository_provider,
        )

    monkeypatch.setattr(main, "build_vnext_services", capture_builder)
    monkeypatch.setattr(main, "initialize_vnext_services", no_op)
    monkeypatch.setattr(main, "build_vnext_runtime", lambda **_kwargs: object())

    async def exercise_lifespan() -> None:
        async with main.lifespan(main.app):
            services = main.app.state.vnext_services
            guide_service = services.hero_guide.__self__
            assert guide_service._cache._client is redis
            assert redis.hgetall_calls == []

    original_app_state = main.app.state._state.copy()
    try:
        asyncio.run(exercise_lifespan())
    finally:
        main.app.state._state.clear()
        main.app.state._state.update(original_app_state)

    assert redis_urls == ["redis://fixture.invalid/0"]
    assert redis.ping_calls == 1
    assert redis.close_calls == 1
    assert len(captured_caches) == 1
    assert captured_caches[0]._client is redis
    assert redis.hgetall_calls == []
