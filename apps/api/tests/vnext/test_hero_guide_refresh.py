from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.vnext.capabilities.hero.guide import PubGuide
from app.vnext.hero_guides import refresh as refresh_module
from app.vnext.hero_guides.cache import (
    GuideCacheSnapshot,
    HeroGuideCacheUnavailableError,
    RedisHeroGuideCache,
)
from app.vnext.hero_guides.refresh import HeroGuideRefresher
from app.vnext.providers.d2pt import D2PTHTTPError, D2PTResponse, D2PTTimeoutError

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "d2pt"
_NOW = datetime(2026, 9, 28, 3, 0, tzinfo=UTC)


def _response(data: list[dict[str, Any]], *, raw_body: bytes | None = None) -> D2PTResponse:
    if raw_body is None:
        raw_body = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return D2PTResponse(
        raw_body=raw_body,
        data=data,
        retrieved_at=_NOW,
        content_type="application/json",
    )


class FakeClient:
    def __init__(
        self,
        heroes: tuple[int, ...] = (18,),
        outcomes: dict[tuple[object, ...], object] | None = None,
        *,
        events: list[tuple[object, ...]] | None = None,
    ) -> None:
        self.heroes = heroes
        self.outcomes = {} if outcomes is None else dict(outcomes)
        self.events = events
        self.calls: list[tuple[object, ...]] = []
        self.thread_ids: list[int] = []
        self.max_active = 0
        self._active = 0
        self._lock = threading.Lock()

    def heroes_list(self) -> D2PTResponse:
        rows = [{"hero_id": hero_id} for hero_id in self.heroes]
        return self._invoke(("heroes_list",), rows)

    def pub_builds(self, hero_id: int, position: int) -> D2PTResponse:
        return self._invoke(("pub_builds", hero_id, position), [])

    def pro_builds(self, hero_id: int) -> D2PTResponse:
        return self._invoke(("pro_builds", hero_id), [])

    def _invoke(
        self,
        call: tuple[object, ...],
        default_data: list[dict[str, Any]],
    ) -> D2PTResponse:
        with self._lock:
            self.calls.append(call)
            self.thread_ids.append(threading.get_ident())
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        if self.events is not None:
            self.events.append(("request", *call))
        try:
            outcome = self.outcomes.get(call, _response(default_data))
            if isinstance(outcome, BaseException):
                raise outcome
            assert isinstance(outcome, D2PTResponse)
            return outcome
        finally:
            with self._lock:
                self._active -= 1


class FakeCache:
    def __init__(self, *, events: list[tuple[object, ...]] | None = None) -> None:
        self.events = events
        self.snapshots: dict[tuple[str, int, int | None], GuideCacheSnapshot] = {}
        self.attempts: list[tuple[str, int, int | None, datetime, str | None]] = []
        self.fail_publish: BaseException | None = None
        self.fail_record: BaseException | None = None

    async def publish(self, snapshot: GuideCacheSnapshot, *, attempted_at: datetime) -> None:
        if self.fail_publish is not None:
            raise self.fail_publish
        key = (snapshot.sample_type, snapshot.hero_id, snapshot.position)
        self.snapshots[key] = snapshot
        self.attempts.append((*key, attempted_at, None))
        if self.events is not None:
            self.events.append(("publish", *key))

    async def record_failure(
        self,
        *,
        sample_type: str,
        hero_id: int,
        position: int | None = None,
        attempted_at: datetime,
        error_code: str,
    ) -> None:
        if self.fail_record is not None:
            raise self.fail_record
        self.attempts.append((sample_type, hero_id, position, attempted_at, error_code))
        if self.events is not None:
            self.events.append(("failure", sample_type, hero_id, position, error_code))


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}

    async def hset(self, key: str, *, mapping: dict[str, str]) -> int:
        target = self.hashes.setdefault(key, {})
        added = sum(field not in target for field in mapping)
        target.update(mapping)
        return added

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))


class StepClock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> datetime:
        value = _NOW + timedelta(seconds=self.calls)
        self.calls += 1
        return value


def _sleeper(events: list[tuple[object, ...]] | None = None) -> tuple[list[float], Any]:
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)
        if events is not None:
            events.append(("sleep", delay))

    return delays, sleep


def _run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def test_refreshes_heroes_and_partitions_in_order_with_one_second_between_requests() -> None:
    events: list[tuple[object, ...]] = []
    client = FakeClient(heroes=(18, 19), events=events)
    cache = FakeCache(events=events)
    delays, sleep = _sleeper(events)
    main_thread_id = threading.get_ident()

    report = _run(HeroGuideRefresher(client, cache, clock=lambda: _NOW, sleep=sleep).refresh_all())

    expected_calls: list[tuple[object, ...]] = [("heroes_list",)]
    for hero_id in (18, 19):
        expected_calls.extend(("pub_builds", hero_id, position) for position in range(1, 6))
        expected_calls.append(("pro_builds", hero_id))
    assert client.calls == expected_calls
    assert report.request_count == 13
    assert report.hero_count == 2
    assert report.status == "success"
    assert report.pub_published == 10
    assert report.pro_published == 2
    assert report.pub_empty == 10
    assert report.pro_empty == 2
    assert delays == [1.0] * 13
    assert client.max_active == 1
    assert all(thread_id != main_thread_id for thread_id in client.thread_ids)
    for index, event in enumerate(events):
        if event[0] == "request":
            assert events[index + 1] == ("sleep", 1.0)


def test_each_successful_request_sleeps_then_parses_and_publishes_before_next_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[object, ...]] = []
    client = FakeClient(heroes=(18,), events=events)
    cache = FakeCache(events=events)
    delays, sleep = _sleeper(events)
    parse_pub = refresh_module.parse_pub_builds
    parse_pro = refresh_module.parse_pro_examples

    def track_pub(
        rows: list[dict[str, Any]],
        *,
        hero_id: int,
        position: int,
    ) -> list[PubGuide]:
        events.append(("parse_pub", hero_id, position))
        return parse_pub(rows, hero_id=hero_id, position=position)

    def track_pro(rows: list[dict[str, Any]], *, hero_id: int) -> list[Any]:
        events.append(("parse_pro", hero_id))
        return parse_pro(rows, hero_id=hero_id)

    monkeypatch.setattr(refresh_module, "parse_pub_builds", track_pub)
    monkeypatch.setattr(refresh_module, "parse_pro_examples", track_pro)
    _run(HeroGuideRefresher(client, cache, clock=lambda: _NOW, sleep=sleep).refresh_all())

    expected = [("request", "heroes_list"), ("sleep", 1.0)]
    for position in range(1, 6):
        expected.extend(
            [
                ("request", "pub_builds", 18, position),
                ("sleep", 1.0),
                ("parse_pub", 18, position),
                ("publish", "pub", 18, position),
            ]
        )
    expected.extend(
        [
            ("request", "pro_builds", 18),
            ("sleep", 1.0),
            ("parse_pro", 18),
            ("publish", "pro", 18, None),
        ]
    )
    assert events == expected
    assert delays == [1.0] * 7


def test_publishes_fixture_bytes_source_rows_and_parsed_projections() -> None:
    pub_raw = (_FIXTURE_DIR / "pub_sven_pos1.json").read_bytes()
    pro_raw = (_FIXTURE_DIR / "pro_sven.json").read_bytes()
    pub_rows = json.loads(pub_raw)
    pro_rows = json.loads(pro_raw)
    client = FakeClient(
        outcomes={
            ("pub_builds", 18, 1): _response(pub_rows, raw_body=pub_raw),
            ("pro_builds", 18): _response(pro_rows, raw_body=pro_raw),
        }
    )
    cache = FakeCache()
    _, sleep = _sleeper()

    report = _run(HeroGuideRefresher(client, cache, clock=lambda: _NOW, sleep=sleep).refresh_all())

    pub_snapshot = cache.snapshots[("pub", 18, 1)]
    pro_snapshot = cache.snapshots[("pro", 18, None)]
    assert pub_snapshot.raw_body == pub_raw
    assert pub_snapshot.source_rows == pub_rows
    assert pub_snapshot.pub_guides
    assert pro_snapshot.raw_body == pro_raw
    assert pro_snapshot.source_rows == pro_rows
    assert pro_snapshot.pro_examples
    assert report.pub_empty == 4
    assert report.pro_empty == 0


def test_successful_empty_responses_are_published_and_counted_as_empty() -> None:
    client = FakeClient()
    cache = FakeCache()
    _, sleep = _sleeper()

    report = _run(HeroGuideRefresher(client, cache, clock=lambda: _NOW, sleep=sleep).refresh_all())

    assert report.status == "success"
    assert report.pub_empty == 5
    assert report.pro_empty == 1
    assert cache.snapshots[("pub", 18, 1)].raw_body == b"[]"
    assert cache.snapshots[("pro", 18, None)].source_rows == []


def test_nonempty_pro_rows_without_recent_matches_are_not_counted_as_empty() -> None:
    source_rows = [{"hero_id": 18, "position": "pos 1", "recent_matches": []}]
    client = FakeClient(outcomes={("pro_builds", 18): _response(source_rows)})
    cache = FakeCache()
    _, sleep = _sleeper()

    report = _run(HeroGuideRefresher(client, cache, clock=lambda: _NOW, sleep=sleep).refresh_all())

    assert report.pro_published == 1
    assert report.pro_empty == 0
    snapshot = cache.snapshots[("pro", 18, None)]
    assert snapshot.source_rows == source_rows
    assert snapshot.pro_examples == []


@pytest.mark.parametrize(
    ("error", "error_code"),
    [(D2PTTimeoutError(), "timeout"), (D2PTHTTPError(403), "http_error")],
)
def test_heroes_list_failure_waits_once_and_does_not_write_cache(
    error: BaseException,
    error_code: str,
) -> None:
    client = FakeClient(outcomes={("heroes_list",): error})
    cache = FakeCache()
    delays, sleep = _sleeper()

    report = _run(HeroGuideRefresher(client, cache, clock=lambda: _NOW, sleep=sleep).refresh_all())

    assert report.status == "failed"
    assert report.request_count == 1
    assert report.hero_count == 0
    assert report.heroes_error == error_code
    assert delays == [1.0]
    assert cache.snapshots == {}
    assert cache.attempts == []


def test_pub_request_failure_is_recorded_and_remaining_partitions_continue() -> None:
    events: list[tuple[object, ...]] = []
    client = FakeClient(
        heroes=(18, 19),
        outcomes={("pub_builds", 18, 1): D2PTTimeoutError()},
        events=events,
    )
    cache = FakeCache(events=events)
    clock = StepClock()
    delays, sleep = _sleeper(events)

    report = _run(HeroGuideRefresher(client, cache, clock=clock, sleep=sleep).refresh_all())

    assert client.calls[:4] == [
        ("heroes_list",),
        ("pub_builds", 18, 1),
        ("pub_builds", 18, 2),
        ("pub_builds", 18, 3),
    ]
    assert client.calls[-7:] == [
        ("pro_builds", 18),
        ("pub_builds", 19, 1),
        ("pub_builds", 19, 2),
        ("pub_builds", 19, 3),
        ("pub_builds", 19, 4),
        ("pub_builds", 19, 5),
        ("pro_builds", 19),
    ]
    assert client.calls[2:7] == [
        ("pub_builds", 18, 2),
        ("pub_builds", 18, 3),
        ("pub_builds", 18, 4),
        ("pub_builds", 18, 5),
        ("pro_builds", 18),
    ]
    assert report.status == "partial"
    assert delays == [1.0] * 13
    assert report.request_count == 13
    assert report.failures[0].error_code == "timeout"
    assert report.failures[0].sample_type == "pub"
    assert report.failures[0].position == 1
    assert cache.attempts[0] == ("pub", 18, 1, _NOW + timedelta(seconds=1), "timeout")
    assert delays == [1.0] * 13
    assert events[2:5] == [
        ("request", "pub_builds", 18, 1),
        ("sleep", 1.0),
        ("failure", "pub", 18, 1, "timeout"),
    ]
    assert events[5] == ("request", "pub_builds", 18, 2)


def test_parser_failure_is_recorded_after_request_delay_and_does_not_publish_partition() -> None:
    invalid_rows = [{"hero_id": 18, "position": "pos 1", "build_data": {"talents": "bad"}}]
    client = FakeClient(outcomes={("pub_builds", 18, 1): _response(invalid_rows)})
    cache = FakeCache()
    events: list[tuple[object, ...]] = []
    client.events = events
    cache.events = events
    delays, sleep = _sleeper(events)

    report = _run(HeroGuideRefresher(client, cache, clock=lambda: _NOW, sleep=sleep).refresh_all())

    assert report.status == "partial"
    assert report.failures[0].error_code == "invalid_guide_data"
    assert ("pub", 18, 1) not in cache.snapshots
    assert delays == [1.0] * report.request_count
    request_index = events.index(("request", "pub_builds", 18, 1))
    sleep_index = events.index(("sleep", 1.0), request_index)
    failure_index = events.index(("failure", "pub", 18, 1, "invalid_guide_data"))
    assert sleep_index < failure_index


def test_pro_request_failure_does_not_skip_following_heroes() -> None:
    client = FakeClient(heroes=(18, 19), outcomes={("pro_builds", 18): D2PTHTTPError(503)})
    cache = FakeCache()
    _, sleep = _sleeper()

    report = _run(HeroGuideRefresher(client, cache, clock=lambda: _NOW, sleep=sleep).refresh_all())

    assert ("pro_builds", 18) in client.calls
    assert client.calls[-7:] == [
        ("pro_builds", 18),
        ("pub_builds", 19, 1),
        ("pub_builds", 19, 2),
        ("pub_builds", 19, 3),
        ("pub_builds", 19, 4),
        ("pub_builds", 19, 5),
        ("pro_builds", 19),
    ]
    assert report.status == "partial"
    assert len(report.failures) == 1
    assert report.failures[0].sample_type == "pro"
    assert report.failures[0].hero_id == 18
    assert report.failures[0].error_code == "http_error"


def test_all_partition_failures_produce_failed_report() -> None:
    outcomes = {
        ("pub_builds", 18, position): D2PTTimeoutError() for position in range(1, 6)
    }
    outcomes[("pro_builds", 18)] = D2PTTimeoutError()
    client = FakeClient(outcomes=outcomes)
    cache = FakeCache()
    delays, sleep = _sleeper()

    report = _run(HeroGuideRefresher(client, cache, clock=lambda: _NOW, sleep=sleep).refresh_all())

    assert report.status == "failed"
    assert report.request_count == 7
    assert report.pub_published == report.pro_published == 0
    assert len(report.failures) == 6
    assert len(cache.attempts) == 6
    assert delays == [1.0] * 7


def test_unexpected_client_exception_propagates_without_failure_record_or_retry() -> None:
    client = FakeClient(outcomes={("heroes_list",): RuntimeError("bug")})
    cache = FakeCache()
    delays, sleep = _sleeper()

    with pytest.raises(RuntimeError, match="bug"):
        _run(HeroGuideRefresher(client, cache, clock=lambda: _NOW, sleep=sleep).refresh_all())

    assert client.calls == [("heroes_list",)]
    assert delays == []
    assert cache.attempts == []


def test_cancellation_during_inter_request_wait_propagates_without_more_requests() -> None:
    client = FakeClient()
    cache = FakeCache()
    sleeps: list[float] = []

    async def cancel_sleep(delay: float) -> None:
        sleeps.append(delay)
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        _run(
            HeroGuideRefresher(
                client,
                cache,
                clock=lambda: _NOW,
                sleep=cancel_sleep,
            ).refresh_all()
        )

    assert client.calls == [("heroes_list",)]
    assert sleeps == [1.0]
    assert cache.snapshots == {}


def test_cache_write_failure_propagates_and_aborts_refresh() -> None:
    client = FakeClient()
    cache = FakeCache()
    cache.fail_publish = HeroGuideCacheUnavailableError()
    _, sleep = _sleeper()

    with pytest.raises(HeroGuideCacheUnavailableError):
        _run(HeroGuideRefresher(client, cache, clock=lambda: _NOW, sleep=sleep).refresh_all())

    assert client.calls == [("heroes_list",), ("pub_builds", 18, 1)]
    assert cache.attempts == []


def test_failure_record_write_error_propagates_without_retry_or_next_request() -> None:
    client = FakeClient(outcomes={("pub_builds", 18, 1): D2PTTimeoutError()})
    cache = FakeCache()
    cache.fail_record = HeroGuideCacheUnavailableError()
    _, sleep = _sleeper()

    with pytest.raises(HeroGuideCacheUnavailableError):
        _run(HeroGuideRefresher(client, cache, clock=lambda: _NOW, sleep=sleep).refresh_all())

    assert client.calls == [("heroes_list",), ("pub_builds", 18, 1)]
    assert cache.attempts == []


def test_report_contains_only_stable_error_code_not_exception_text() -> None:
    error = D2PTTimeoutError()
    error.args = ("PRIVATE_URL_AND_CREDENTIAL",)
    client = FakeClient(outcomes={("pub_builds", 18, 1): error})
    cache = FakeCache()
    _, sleep = _sleeper()

    report = _run(HeroGuideRefresher(client, cache, clock=lambda: _NOW, sleep=sleep).refresh_all())

    assert report.failures[0].error_code == "timeout"
    assert "PRIVATE_URL_AND_CREDENTIAL" not in repr(report)


def test_redis_cache_preserves_old_snapshot_then_replaces_and_clears_error() -> None:
    redis = FakeRedis()
    cache = RedisHeroGuideCache(redis)
    old_snapshot = GuideCacheSnapshot(
        sample_type="pub",
        hero_id=18,
        position=1,
        retrieved_at=_NOW,
        content_type="application/json",
        raw_body=b"old snapshot",
        source_rows=[{"hero_id": 18, "position": "pos 1", "build_data": {}}],
        pub_guides=[PubGuide(build_id=1)],
    )

    async def seed_old_snapshot() -> None:
        await cache.publish(old_snapshot, attempted_at=_NOW)

    _run(seed_old_snapshot())
    failed_client = FakeClient(outcomes={("pub_builds", 18, 1): D2PTTimeoutError()})
    _, sleep = _sleeper()
    failed_report = _run(
        HeroGuideRefresher(failed_client, cache, clock=lambda: _NOW, sleep=sleep).refresh_all()
    )
    after_failure = _run(cache.get_pub(hero_id=18, position=1))

    replacement_rows = [{"hero_id": 18, "position": "pos 1", "build_id": 2, "build_data": {}}]
    replacement_raw = b'[{ "hero_id":18,"position":"pos 1","build_id":2,"build_data":{} }]'
    success_client = FakeClient(
        outcomes={
            ("pub_builds", 18, 1): _response(replacement_rows, raw_body=replacement_raw)
        }
    )
    _, sleep = _sleeper()
    success_report = _run(
        HeroGuideRefresher(success_client, cache, clock=lambda: _NOW, sleep=sleep).refresh_all()
    )
    after_success = _run(cache.get_pub(hero_id=18, position=1))

    assert failed_report.status == "partial"
    assert after_failure.snapshot == old_snapshot
    assert after_failure.last_error == "timeout"
    assert success_report.status == "success"
    assert after_success.snapshot is not None
    assert after_success.snapshot.raw_body == replacement_raw
    assert after_success.snapshot.pub_guides[0].build_id == 2
    assert after_success.last_error is None


def test_refresh_report_and_partition_attempts_use_aware_clock_values() -> None:
    client = FakeClient()
    cache = FakeCache()
    clock = StepClock()
    _, sleep = _sleeper()

    report = _run(HeroGuideRefresher(client, cache, clock=clock, sleep=sleep).refresh_all())

    assert report.started_at == _NOW
    assert report.finished_at == _NOW + timedelta(seconds=7)
    assert [attempt[3] for attempt in cache.attempts] == [
        _NOW + timedelta(seconds=index) for index in range(1, 7)
    ]
    assert cache.snapshots[("pub", 18, 1)].retrieved_at == _NOW
    assert cache.attempts[0][3] != cache.snapshots[("pub", 18, 1)].retrieved_at
    assert not hasattr(cache, "get_pub")


def test_naive_clock_value_fails_before_making_a_request() -> None:
    client = FakeClient()
    cache = FakeCache()
    _, sleep = _sleeper()

    with pytest.raises(ValueError, match="timezone-aware"):
        _run(
            HeroGuideRefresher(
                client,
                cache,
                clock=lambda: datetime(2026, 9, 28),
                sleep=sleep,
            ).refresh_all()
        )

    assert client.calls == []
