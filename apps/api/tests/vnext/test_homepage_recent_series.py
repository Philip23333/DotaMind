from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from app.api.v1.home_routes import router
from app.vnext.capabilities.esports.dtos import TeamDTO
from app.vnext.capabilities.esports.team import TeamSearchResult
from app.vnext.composition import VNextServices, VNextSettings, build_vnext_services
from app.vnext.homepage.recent_series import (
    HomepageRecentSeriesService,
    RecentSeriesCacheEntry,
    RecentSeriesSnapshot,
    RedisRecentSeriesCache,
)
from app.vnext.providers.pandascore.series_lifecycle import (
    SeriesLifecycleItem,
    SeriesLifecycleResult,
)

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.hset_calls: list[tuple[str, dict[str, str]]] = []
        self.read_count = 0
        self.read_events: dict[int, asyncio.Event] = {}
        self.hset_failures_remaining = 0

    def watch_reads(self, target: int) -> asyncio.Event:
        event = asyncio.Event()
        if self.read_count >= target:
            event.set()
        self.read_events[target] = event
        return event

    async def hgetall(self, key: str) -> dict[str, str]:
        self.read_count += 1
        for target, event in self.read_events.items():
            if self.read_count >= target:
                event.set()
        return dict(self.hashes.get(key, {}))

    async def hset(self, key: str, *, mapping: dict[str, str]) -> int:
        if self.hset_failures_remaining:
            self.hset_failures_remaining -= 1
            raise RedisError("test Redis write failure")
        self.hset_calls.append((key, dict(mapping)))
        target = self.hashes.setdefault(key, {})
        added = sum(field not in target for field in mapping)
        target.update(mapping)
        return added


class FakeProvider:
    def __init__(self, running: list[SeriesLifecycleItem], past: list[SeriesLifecycleItem]) -> None:
        self.results = {"running": running, "past": past}
        self.calls: list[tuple[str, int, int]] = []
        self.fail_with: Exception | None = None
        self.started = asyncio.Event()
        self.release: asyncio.Event | None = None
        self.cleaned = asyncio.Event()
        self.active_calls = 0
        self.max_active_calls = 0

    async def read_lifecycle(self, *, lifecycle: str, page: int, limit: int):
        self.calls.append((lifecycle, page, limit))
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        self.started.set()
        try:
            if self.release is None:
                await asyncio.sleep(0)
            else:
                await self.release.wait()
            if self.fail_with is not None:
                raise self.fail_with
            return SeriesLifecycleResult(
                items=self.results[lifecycle],
                page=page,
                limit=limit,
            )
        finally:
            self.active_calls -= 1
            self.cleaned.set()


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _series(
    series_id: int,
    *,
    begin_at: str | None = "2026-09-01T00:00:00Z",
    end_at: str | None = "2026-09-02T00:00:00Z",
    full_name: str | None = None,
    name: str | None = None,
    winner_id: int | None = None,
    winner_type: str | None = None,
) -> SeriesLifecycleItem:
    return SeriesLifecycleItem(
        id=series_id,
        league_id=20,
        name=name or f"Series {series_id}",
        full_name=full_name,
        begin_at=begin_at,
        end_at=end_at,
        winner_id=winner_id,
        winner_type=winner_type,
    )


def _service(
    provider: FakeProvider,
    cache: RedisRecentSeriesCache,
    *,
    clock: Clock | None = None,
    team_ids: set[int] | None = None,
) -> HomepageRecentSeriesService:
    resolved_team_ids = team_ids or set()
    team_calls: list[int] = []

    async def search_team(query) -> TeamSearchResult:
        team_calls.append(query.id)
        matches = (
            [TeamDTO(id=query.id, name=f" Team {query.id} ")]
            if query.id in resolved_team_ids
            else []
        )
        return TeamSearchResult(items=matches, page=query.page, limit=query.limit)

    service = HomepageRecentSeriesService(
        read_lifecycle=provider.read_lifecycle,
        search_team=search_team,
        cache=cache,
        now=clock,
    )
    service.team_calls = team_calls
    return service


def test_candidate_order_dedupes_and_resolves_only_explicit_team_winners() -> None:
    provider = FakeProvider(
        running=[
            _series(1, begin_at="2026-09-01T00:00:00Z"),
            _series(2, begin_at="2026-09-03T00:00:00Z"),
            _series(3, begin_at=None),
        ],
        past=[
            _series(1, begin_at="2026-08-01T00:00:00Z", end_at="2026-09-30T00:00:00Z"),
            _series(4, end_at="2026-09-10T00:00:00Z", winner_id=70, winner_type="Team"),
            _series(5, end_at="2026-09-20T00:00:00Z", winner_id=71, winner_type="Player"),
            _series(6, end_at="2026-09-15T00:00:00Z", winner_id=72, winner_type="Mystery"),
            _series(7, end_at="2026-09-25T00:00:00Z", winner_id=70, winner_type="Team"),
        ],
    )
    service = _service(provider, RedisRecentSeriesCache(FakeRedis()), team_ids={70})

    response = asyncio.run(service.get_recent_series())

    assert response.status == "fresh"
    assert [item.series_id for item in response.items] == [2, 1, 3, 7, 5, 6, 4]
    assert [item.lifecycle for item in response.items] == [
        "running",
        "running",
        "running",
        "past",
        "past",
        "past",
        "past",
    ]
    assert response.items[3].champion_name == "Team 70"
    assert response.items[4].champion_name is None
    assert response.items[5].champion_name is None
    assert response.items[6].champion_name == "Team 70"
    assert service.team_calls == [70]
    assert provider.calls == [("running", 1, 100), ("past", 1, 100)]


def test_candidate_cap_and_missing_dates_sort_after_dated_items() -> None:
    provider = FakeProvider(
        running=[_series(i, begin_at=None) for i in range(1, 4)]
        + [_series(i, begin_at=f"2026-09-{i:02d}T00:00:00Z") for i in range(4, 13)],
        past=[_series(i, end_at=f"2026-09-{i:02d}T00:00:00Z") for i in range(20, 25)],
    )
    service = _service(provider, RedisRecentSeriesCache(FakeRedis()))

    response = asyncio.run(service.get_recent_series())

    assert len(response.items) == 10
    assert [item.series_id for item in response.items] == [12, 11, 10, 9, 8, 7, 6, 5, 4, 1]


def test_valid_empty_data_is_cached_and_distinct_from_source_failure() -> None:
    provider = FakeProvider([], [])
    redis = FakeRedis()
    clock = Clock()
    service = _service(provider, RedisRecentSeriesCache(redis), clock=clock)

    first = asyncio.run(service.get_recent_series())
    second = asyncio.run(service.get_recent_series())

    assert first.status == "fresh"
    assert first.items == []
    assert first.last_error is None
    assert second.status == "fresh"
    assert len(provider.calls) == 2


def test_stale_success_is_returned_after_provider_failure() -> None:
    async def run() -> None:
        provider = FakeProvider([_series(1)], [])
        redis = FakeRedis()
        clock = Clock()
        service = _service(provider, RedisRecentSeriesCache(redis), clock=clock)

        first = await service.get_recent_series()
        clock.value += timedelta(seconds=601)
        provider.fail_with = httpx.ConnectError("private provider detail")
        stale = await service.get_recent_series()
        refresh_task = service._refresh_task
        assert refresh_task is not None
        await refresh_task
        after_failure = await service.get_recent_series()

        assert first.status == "fresh"
        assert stale.status == "stale"
        assert [item.series_id for item in stale.items] == [1]
        assert stale.retrieved_at == first.retrieved_at
        assert stale.last_error is None
        assert after_failure.last_error == "transport_error"
        assert redis.hashes["dotamind:vnext:homepage:recent-series:v1"]["snapshot"]
        await service.aclose()

    asyncio.run(run())


def test_no_previous_snapshot_reports_provider_failure_as_unavailable() -> None:
    provider = FakeProvider([], [])
    provider.fail_with = httpx.ConnectError("private provider detail")
    service = _service(provider, RedisRecentSeriesCache(FakeRedis()))

    response = asyncio.run(service.get_recent_series())

    assert response.status == "unavailable"
    assert response.items == []
    assert response.last_error == "transport_error"


def test_rows_all_unmappable_are_not_treated_as_a_valid_empty_list() -> None:
    provider = FakeProvider([], [])

    async def invalid_response(*, lifecycle: str, page: int, limit: int):
        from app.vnext.capabilities.esports.dtos import ResponseAnomaly

        return SeriesLifecycleResult(
            items=[],
            page=page,
            limit=limit,
            anomalies=[ResponseAnomaly(path="provider.items[0]", reason="bad row")],
        )

    provider.read_lifecycle = invalid_response
    response = asyncio.run(
        _service(provider, RedisRecentSeriesCache(FakeRedis())).get_recent_series()
    )

    assert response.status == "unavailable"
    assert response.last_error == "invalid_response"


def test_overlapping_requests_share_one_refresh() -> None:
    provider = FakeProvider([_series(1)], [])
    service = _service(provider, RedisRecentSeriesCache(FakeRedis()))

    async def run_both():
        return await asyncio.gather(
            service.get_recent_series(),
            service.get_recent_series(),
        )

    first, second = asyncio.run(run_both())

    assert first.status == second.status == "fresh"
    assert len(provider.calls) == 2
    assert provider.max_active_calls == 1


def test_expired_snapshot_returns_immediately_while_refresh_is_blocked() -> None:
    async def run() -> None:
        redis = FakeRedis()
        cache = RedisRecentSeriesCache(redis)
        old_snapshot = RecentSeriesSnapshot(
            items=[
                {
                    "series_id": 1,
                    "name": "Old Series",
                    "lifecycle": "running",
                }
            ],
            retrieved_at=NOW - timedelta(seconds=601),
        )
        await cache.publish(old_snapshot, attempted_at=old_snapshot.retrieved_at)
        provider = FakeProvider([_series(2)], [])
        provider.release = asyncio.Event()
        clock = Clock()
        service = _service(provider, cache, clock=clock)

        response = await service.get_recent_series()
        await provider.started.wait()

        assert response.status == "stale"
        assert [item.series_id for item in response.items] == [1]
        assert not provider.release.is_set()
        refresh_task = service._refresh_task
        assert refresh_task is not None and not refresh_task.done()

        provider.release.set()
        await refresh_task
        refreshed = await service.get_recent_series()
        assert refreshed.status == "fresh"
        assert [item.series_id for item in refreshed.items] == [2]
        await service.aclose()

    asyncio.run(run())


def test_expired_successful_empty_snapshot_uses_stale_refresh_path() -> None:
    async def run() -> None:
        cache = RedisRecentSeriesCache(FakeRedis())
        snapshot = RecentSeriesSnapshot(items=[], retrieved_at=NOW - timedelta(seconds=601))
        await cache.publish(snapshot, attempted_at=snapshot.retrieved_at)
        provider = FakeProvider([], [])
        provider.release = asyncio.Event()
        service = _service(provider, cache, clock=Clock())

        stale = await service.get_recent_series()
        await provider.started.wait()
        assert stale.status == "stale"
        assert stale.items == []
        refresh_task = service._refresh_task
        assert refresh_task is not None and not refresh_task.done()

        provider.release.set()
        await refresh_task
        fresh = await service.get_recent_series()
        assert fresh.status == "fresh"
        assert fresh.items == []
        await service.aclose()

    asyncio.run(run())


def test_concurrent_stale_requests_share_one_background_refresh() -> None:
    async def run() -> None:
        cache = RedisRecentSeriesCache(FakeRedis())
        snapshot = RecentSeriesSnapshot(
            items=[{"series_id": 1, "name": "Old", "lifecycle": "running"}],
            retrieved_at=NOW - timedelta(seconds=601),
        )
        await cache.publish(snapshot, attempted_at=snapshot.retrieved_at)
        provider = FakeProvider([_series(2)], [])
        provider.release = asyncio.Event()
        service = _service(provider, cache, clock=Clock())

        responses = await asyncio.gather(
            *(service.get_recent_series() for _ in range(5))
        )
        await provider.started.wait()

        assert all(response.status == "stale" for response in responses)
        assert all(response.items[0].series_id == 1 for response in responses)
        assert len(provider.calls) == 1
        assert provider.max_active_calls == 1
        refresh_task = service._refresh_task
        assert refresh_task is not None
        provider.release.set()
        await refresh_task
        assert len(provider.calls) == 2
        await service.aclose()

    asyncio.run(run())


def test_cancelling_one_cold_cache_waiter_does_not_cancel_shared_refresh() -> None:
    async def run() -> None:
        redis = FakeRedis()
        service_cache = RedisRecentSeriesCache(redis)
        provider = FakeProvider([_series(4)], [])
        provider.release = asyncio.Event()
        service = _service(provider, service_cache, clock=Clock())

        first_waiter = asyncio.create_task(service.get_recent_series())
        await provider.started.wait()
        shared_refresh = service._refresh_task
        assert shared_refresh is not None

        fourth_cache_read = redis.watch_reads(4)
        second_waiter = asyncio.create_task(service.get_recent_series())
        await fourth_cache_read.wait()
        first_waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first_waiter
        assert not shared_refresh.cancelled()
        assert not shared_refresh.done()

        provider.release.set()
        response = await second_waiter
        assert response.status == "fresh"
        assert [item.series_id for item in response.items] == [4]
        assert len(provider.calls) == 2
        assert provider.max_active_calls == 1
        await service.aclose()

    asyncio.run(run())


def test_failed_refresh_cooldown_survives_service_reconstruction() -> None:
    async def run() -> None:
        cache = RedisRecentSeriesCache(FakeRedis())
        snapshot = RecentSeriesSnapshot(
            items=[{"series_id": 1, "name": "Old", "lifecycle": "running"}],
            retrieved_at=NOW - timedelta(seconds=601),
        )
        await cache.publish(snapshot, attempted_at=snapshot.retrieved_at)
        clock = Clock()
        first_provider = FakeProvider([], [])
        first_provider.fail_with = httpx.ConnectError("private provider detail")
        first_service = _service(first_provider, cache, clock=clock)

        first_response = await first_service.get_recent_series()
        failed_task = first_service._refresh_task
        assert first_response.status == "stale"
        assert failed_task is not None
        await failed_task
        assert first_provider.calls == [("running", 1, 100)]
        assert (await cache.get()).last_error == "transport_error"

        clock.value += timedelta(seconds=599)
        still_throttled = await first_service.get_recent_series()
        assert still_throttled.status == "stale"
        assert first_provider.calls == [("running", 1, 100)]

        second_provider = FakeProvider([], [])
        second_provider.fail_with = httpx.ConnectError("private provider detail")
        second_service = _service(second_provider, cache, clock=clock)
        reconstructed_still_throttled = await second_service.get_recent_series()
        assert reconstructed_still_throttled.status == "stale"
        assert second_provider.calls == []

        clock.value += timedelta(seconds=1)
        retry_response = await second_service.get_recent_series()
        retry_task = second_service._refresh_task
        assert retry_response.status == "stale"
        assert retry_task is not None
        await retry_task
        assert second_provider.calls == [("running", 1, 100)]
        await first_service.aclose()
        await second_service.aclose()

    asyncio.run(run())


def test_cold_failure_returns_unavailable_and_retries_at_600_seconds() -> None:
    async def run() -> None:
        provider = FakeProvider([], [])
        provider.fail_with = httpx.ConnectError("private provider detail")
        clock = Clock()
        service = _service(provider, RedisRecentSeriesCache(FakeRedis()), clock=clock)

        first = await service.get_recent_series()
        assert first.status == "unavailable"
        assert first.last_error == "transport_error"
        assert provider.calls == [("running", 1, 100)]

        clock.value += timedelta(seconds=599)
        throttled = await service.get_recent_series()
        assert throttled.status == "unavailable"
        assert provider.calls == [("running", 1, 100)]

        clock.value += timedelta(seconds=1)
        retried = await service.get_recent_series()
        assert retried.status == "unavailable"
        assert len(provider.calls) == 2
        await service.aclose()

    asyncio.run(run())


def test_local_failure_time_throttles_when_redis_failure_write_fails() -> None:
    async def run() -> None:
        redis = FakeRedis()
        cache = RedisRecentSeriesCache(redis)
        snapshot = RecentSeriesSnapshot(
            items=[{"series_id": 1, "name": "Old", "lifecycle": "running"}],
            retrieved_at=NOW - timedelta(seconds=601),
        )
        await cache.publish(snapshot, attempted_at=snapshot.retrieved_at)
        redis.hset_failures_remaining = 1
        clock = Clock()
        provider = FakeProvider([], [])
        provider.fail_with = httpx.ConnectError("private provider detail")
        service = _service(provider, cache, clock=clock)

        response = await service.get_recent_series()
        failed_task = service._refresh_task
        assert response.status == "stale"
        assert failed_task is not None
        await failed_task
        entry = await cache.get()
        assert entry.last_error is None
        assert service._local_failure == (NOW, "transport_error")

        clock.value += timedelta(seconds=599)
        throttled = await service.get_recent_series()
        assert throttled.status == "stale"
        assert throttled.last_error == "transport_error"
        assert provider.calls == [("running", 1, 100)]

        clock.value += timedelta(seconds=1)
        retry = await service.get_recent_series()
        retry_task = service._refresh_task
        assert retry.status == "stale"
        assert retry_task is not None
        await retry_task
        assert provider.calls == [("running", 1, 100), ("running", 1, 100)]
        await service.aclose()

    asyncio.run(run())


def test_aclose_cancels_refresh_preserves_cache_and_prevents_new_tasks() -> None:
    async def run() -> None:
        redis = FakeRedis()
        cache = RedisRecentSeriesCache(redis)
        snapshot = RecentSeriesSnapshot(
            items=[{"series_id": 1, "name": "Old", "lifecycle": "running"}],
            retrieved_at=NOW - timedelta(seconds=601),
        )
        await cache.publish(snapshot, attempted_at=snapshot.retrieved_at)
        provider = FakeProvider([_series(2)], [])
        provider.release = asyncio.Event()
        clock = Clock()
        service = _service(provider, cache, clock=clock)

        first = await service.get_recent_series()
        await provider.started.wait()
        refresh_task = service._refresh_task
        assert refresh_task is not None and not refresh_task.done()
        await service.aclose()
        await provider.cleaned.wait()
        await asyncio.gather(refresh_task, return_exceptions=True)
        await service.aclose()

        stored = await cache.get()
        assert stored.snapshot == snapshot
        assert stored.last_error is None
        assert len(redis.hset_calls) == 1
        assert service._refresh_task is None
        assert first.status == "stale"

        after_close = await service.get_recent_series()
        assert after_close.status == "stale"
        assert [item.series_id for item in after_close.items] == [1]
        assert provider.calls == [("running", 1, 100)]

    asyncio.run(run())


def test_unexpected_refresh_errors_are_not_reported_as_empty_provider_results() -> None:
    async def run() -> None:
        provider = FakeProvider([], [])
        provider.fail_with = RuntimeError("private implementation detail")
        service = _service(provider, RedisRecentSeriesCache(FakeRedis()), clock=Clock())

        with pytest.raises(RuntimeError, match="private implementation detail"):
            await service.get_recent_series()
        assert provider.calls == [("running", 1, 100)]
        await service.aclose()

    asyncio.run(run())


def test_redis_cache_round_trip_and_failure_keep_successful_snapshot() -> None:
    redis = FakeRedis()
    cache = RedisRecentSeriesCache(redis)
    snapshot = RecentSeriesSnapshot(
        items=[
            {
                "series_id": 10,
                "name": "Series Ten",
                "lifecycle": "past",
                "champion_name": None,
            }
        ],
        retrieved_at=NOW,
    )

    asyncio.run(cache.publish(snapshot, attempted_at=NOW))
    stored = dict(redis.hashes["dotamind:vnext:homepage:recent-series:v1"])
    asyncio.run(
        cache.record_failure(
            attempted_at=NOW + timedelta(minutes=11),
            error_code="timeout",
        )
    )
    entry = asyncio.run(cache.get())

    assert entry.snapshot == snapshot
    assert entry.last_error == "timeout"
    assert entry.last_attempt_at == NOW + timedelta(minutes=11)
    assert "snapshot" not in redis.hset_calls[-1][1]
    cache_key = "dotamind:vnext:homepage:recent-series:v1"
    assert stored["snapshot"] == redis.hashes[cache_key]["snapshot"]
    assert not hasattr(redis, "expire")


def test_home_route_returns_candidates_and_is_unavailable_without_service() -> None:
    provider = FakeProvider([_series(4, full_name="Series Four")], [])
    service = _service(provider, RedisRecentSeriesCache(FakeRedis()))
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.homepage_recent_series = service

    with TestClient(app) as client:
        response = client.get("/api/v1/home/recent-series")

    assert response.status_code == 200
    assert response.json()["status"] == "fresh"
    assert set(response.json()) == {
        "status",
        "items",
        "retrieved_at",
        "last_attempt_at",
        "last_error",
    }
    assert response.json()["items"][0]["series_id"] == 4
    assert response.json()["items"][0]["name"] == "Series Four"

    unavailable_app = FastAPI()
    unavailable_app.include_router(router, prefix="/api/v1")
    with TestClient(unavailable_app) as client:
        unavailable = client.get("/api/v1/home/recent-series")
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "homepage_series_unavailable"


def test_homepage_cache_entry_defaults_to_empty() -> None:
    assert RecentSeriesCacheEntry() == RecentSeriesCacheEntry(
        snapshot=None,
        last_attempt_at=None,
        last_error=None,
    )


def test_composition_registers_homepage_read_service_only_with_shared_cache() -> None:
    without_cache = build_vnext_services(VNextSettings())
    with_cache = build_vnext_services(
        VNextSettings(),
        recent_series_cache=RedisRecentSeriesCache(FakeRedis()),
    )

    assert without_cache.homepage_recent_series is None
    assert isinstance(with_cache.homepage_recent_series, HomepageRecentSeriesService)


def test_vnext_services_close_homepage_service_before_shared_redis(monkeypatch) -> None:
    from redis import asyncio as redis_asyncio

    from app import main

    events: list[str] = []

    class Closeable:
        async def aclose(self) -> None:
            events.append("homepage")

    class FakeRedisClient:
        async def ping(self) -> bool:
            return True

        async def aclose(self) -> None:
            events.append("redis")

    class FakeStore:
        async def aclose(self) -> None:
            events.append("store")

    class FakeDatabase:
        engine = object()
        session_factory = object()

    class FakeEventBus:
        def __init__(self, **_kwargs) -> None:
            pass

        async def ping(self) -> bool:
            return True

        async def aclose(self) -> None:
            events.append("event_bus")

        async def subscribe_cancellations(self, _run_id):
            return

    class FakeManager:
        def __init__(self, **_kwargs) -> None:
            pass

        async def start(self) -> None:
            pass

        async def shutdown(self) -> None:
            pass

    class FakeSweeper:
        def __init__(self, **_kwargs) -> None:
            pass

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    async def no_op_async(*_args, **_kwargs):
        return None

    async def run() -> None:
        redis_client = FakeRedisClient()
        services = VNextServices(homepage_recent_series=Closeable())
        fake_settings = SimpleNamespace(
            redis_url="redis://local-test",
            database_url="postgresql://local-test",
            max_concurrent_chat_runs=1,
            run_heartbeat_seconds=1,
            run_stale_seconds=1,
            run_sweeper_interval_seconds=1,
        )
        conversation = SimpleNamespace(
            recent_dialogue_max_chars=100,
            history_lookup_max_turns=1,
            history_lookup_max_chars=100,
        )
        monkeypatch.setattr(main, "settings", fake_settings)
        monkeypatch.setattr(
            main.VNextSettings,
            "from_env",
            classmethod(lambda cls: VNextSettings()),
        )
        monkeypatch.setattr(main, "get_policy", lambda: SimpleNamespace(conversation=conversation))
        monkeypatch.setattr(main, "_require_trace_recording_redis", lambda *_args: None)
        monkeypatch.setattr(main, "build_image_manifest_reader", lambda _data_dir: None)
        monkeypatch.setattr(main, "create_database_resources", lambda _url: FakeDatabase())
        monkeypatch.setattr(main, "ping_database", no_op_async)
        monkeypatch.setattr(main, "build_session_store", lambda *_args: FakeStore())
        monkeypatch.setattr(main, "PostgresChatRepository", lambda _factory: object())
        monkeypatch.setattr(main, "PostgresChatRunRepository", lambda _factory: object())
        monkeypatch.setattr(main, "RedisTraceStore", lambda *_args, **_kwargs: object())
        monkeypatch.setattr(main, "_hero_guide_cache_for_data_dir", lambda *_args: None)
        monkeypatch.setattr(main, "build_vnext_services", lambda *_args, **_kwargs: services)
        monkeypatch.setattr(main, "initialize_vnext_services", no_op_async)
        monkeypatch.setattr(main, "build_vnext_runtime", lambda **_kwargs: object())
        monkeypatch.setattr(main, "ConversationContextBuilder", lambda: object())
        monkeypatch.setattr(main, "DotaVisualEntityEnricher", lambda *_args: object())
        monkeypatch.setattr(main, "VNextChatService", lambda *_args, **_kwargs: object())
        monkeypatch.setattr(main, "ConversationMemoryService", lambda **_kwargs: object())
        monkeypatch.setattr(main, "RedisRunEventBus", FakeEventBus)
        monkeypatch.setattr(main, "BackgroundRunManager", FakeManager)
        monkeypatch.setattr(main, "ChatRunExecutor", lambda **_kwargs: object())
        monkeypatch.setattr(main, "ChatRunRuntime", lambda **_kwargs: object())
        monkeypatch.setattr(main, "RunStaleSweeper", FakeSweeper)
        monkeypatch.setattr(main, "close_database", no_op_async)
        monkeypatch.setattr(redis_asyncio, "from_url", lambda *_args, **_kwargs: redis_client)

        class FakeApp:
            state = SimpleNamespace()

        async with main.lifespan(FakeApp()):
            pass

        assert events.index("homepage") < events.index("redis")

    asyncio.run(run())
