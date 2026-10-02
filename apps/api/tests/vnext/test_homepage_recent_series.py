from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.home_routes import router
from app.vnext.capabilities.esports.dtos import TeamDTO
from app.vnext.capabilities.esports.team import TeamSearchResult
from app.vnext.composition import VNextSettings, build_vnext_services
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

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def hset(self, key: str, *, mapping: dict[str, str]) -> int:
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

    async def read_lifecycle(self, *, lifecycle: str, page: int, limit: int):
        self.calls.append((lifecycle, page, limit))
        await asyncio.sleep(0)
        if self.fail_with is not None:
            raise self.fail_with
        return SeriesLifecycleResult(
            items=self.results[lifecycle],
            page=page,
            limit=limit,
        )


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
    provider = FakeProvider([_series(1)], [])
    redis = FakeRedis()
    clock = Clock()
    service = _service(provider, RedisRecentSeriesCache(redis), clock=clock)

    first = asyncio.run(service.get_recent_series())
    clock.value += timedelta(seconds=601)
    provider.fail_with = httpx.ConnectError("private provider detail")
    stale = asyncio.run(service.get_recent_series())

    assert first.status == "fresh"
    assert stale.status == "stale"
    assert [item.series_id for item in stale.items] == [1]
    assert stale.retrieved_at == first.retrieved_at
    assert stale.last_error == "transport_error"
    assert redis.hashes["dotamind:vnext:homepage:recent-series:v1"]["snapshot"]


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
