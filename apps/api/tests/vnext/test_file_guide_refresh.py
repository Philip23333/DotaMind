from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.vnext.hero_guides.cache import (
    GuideCacheSnapshot,
    HeroGuideCacheUnavailableError,
)
from app.vnext.hero_guides.file_cache import FileHeroGuideCache
from app.vnext.hero_guides.refresh import HeroGuideRefresher
from app.vnext.providers.d2pt import D2PTResponse, D2PTTimeoutError
from app.vnext.providers.d2pt.parsers import parse_pro_examples, parse_pub_builds

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "d2pt"
_NOW = datetime(2026, 9, 30, 3, 0, tzinfo=UTC)
_ATTEMPTED = _NOW - timedelta(minutes=1)


def _response(
    data: list[dict[str, Any]],
    *,
    raw_body: bytes | None = None,
) -> D2PTResponse:
    if raw_body is None:
        raw_body = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return D2PTResponse(
        raw_body=raw_body,
        data=data,
        retrieved_at=_NOW,
        content_type="application/json",
    )


class FakeD2PTClient:
    def __init__(
        self,
        *,
        heroes: tuple[int, ...] = (18,),
        outcomes: dict[tuple[object, ...], object] | None = None,
        events: list[tuple[object, ...]] | None = None,
    ) -> None:
        self.heroes = heroes
        self.outcomes = {} if outcomes is None else dict(outcomes)
        self.events = events
        self.calls: list[tuple[object, ...]] = []

    def heroes_list(self) -> D2PTResponse:
        return self._invoke(
            ("heroes_list",), [{"hero_id": hero_id} for hero_id in self.heroes]
        )

    def pub_builds(self, hero_id: int, position: int) -> D2PTResponse:
        return self._invoke(("pub_builds", hero_id, position), [])

    def pro_builds(self, hero_id: int) -> D2PTResponse:
        return self._invoke(("pro_builds", hero_id), [])

    def _invoke(
        self,
        call: tuple[object, ...],
        default_data: list[dict[str, Any]],
    ) -> D2PTResponse:
        self.calls.append(call)
        if self.events is not None:
            self.events.append(("request", *call))
        outcome = self.outcomes.get(call, _response(default_data))
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, D2PTResponse)
        return outcome


class StepClock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> datetime:
        result = _NOW + timedelta(seconds=self.calls)
        self.calls += 1
        return result


def _run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def test_real_refresher_publishes_source_bytes_rows_dtos_and_times_to_files(
    tmp_path: Path,
) -> None:
    pub_bytes = (_FIXTURE_DIR / "pub_sven_pos1.json").read_bytes()
    pro_bytes = (_FIXTURE_DIR / "pro_sven.json").read_bytes()
    pub_rows = json.loads(pub_bytes)
    pro_rows = json.loads(pro_bytes)
    events: list[tuple[object, ...]] = []
    client = FakeD2PTClient(
        outcomes={
            ("pub_builds", 18, 1): _response(pub_rows, raw_body=pub_bytes),
            ("pro_builds", 18): _response(pro_rows, raw_body=pro_bytes),
        },
        events=events,
    )
    cache = FileHeroGuideCache(tmp_path)
    clock = StepClock()

    async def sleep(delay: float) -> None:
        events.append(("sleep", delay))

    report = _run(
        HeroGuideRefresher(client, cache, clock=clock, sleep=sleep).refresh_all()
    )

    expected_calls: list[tuple[object, ...]] = [("heroes_list",)]
    expected_calls.extend(("pub_builds", 18, position) for position in range(1, 6))
    expected_calls.append(("pro_builds", 18))
    assert client.calls == expected_calls
    assert report.status == "success"
    assert report.request_count == 7
    assert report.hero_count == 1
    assert report.pub_published == 5
    assert report.pro_published == 1
    assert report.pub_empty == 4
    assert report.pro_empty == 0
    assert clock.calls == 8
    assert report.started_at == _NOW
    assert report.finished_at == _NOW + timedelta(seconds=7)
    expected_events: list[tuple[object, ...]] = [("request", "heroes_list")]
    expected_events.append(("sleep", 1.0))
    for position in range(1, 6):
        expected_events.extend(
            [
                ("request", "pub_builds", 18, position),
                ("sleep", 1.0),
            ]
        )
    expected_events.extend(
        [("request", "pro_builds", 18), ("sleep", 1.0)]
    )
    assert events == expected_events

    pub_entry = _run(cache.get_pub(hero_id=18, position=1))
    pro_entry = _run(cache.get_pro(hero_id=18))
    assert pub_entry.snapshot is not None
    assert pub_entry.snapshot.raw_body == pub_bytes
    assert pub_entry.snapshot.source_rows == pub_rows
    assert pub_entry.snapshot.retrieved_at == _NOW
    assert pub_entry.snapshot.content_type == "application/json"
    assert pub_entry.snapshot.pub_guides == parse_pub_builds(
        pub_rows, hero_id=18, position=1
    )
    assert pub_entry.last_attempt_at == _NOW + timedelta(seconds=1)
    assert pro_entry.snapshot is not None
    assert pro_entry.snapshot.raw_body == pro_bytes
    assert pro_entry.snapshot.source_rows == pro_rows
    assert pro_entry.snapshot.retrieved_at == _NOW
    assert pro_entry.snapshot.content_type == "application/json"
    assert pro_entry.snapshot.pro_examples == parse_pro_examples(pro_rows, hero_id=18)
    assert pro_entry.last_attempt_at == _NOW + timedelta(seconds=6)
    empty_pub = _run(cache.get_pub(hero_id=18, position=2))
    assert empty_pub.snapshot is not None
    assert empty_pub.snapshot.raw_body == b"[]"
    assert empty_pub.snapshot.source_rows == []
    assert empty_pub.snapshot.pub_guides == []
    assert (tmp_path / "guides" / "pub" / "18" / "1.json").is_file()
    assert (tmp_path / "guides" / "pro" / "18.json").is_file()
    assert not (tmp_path / "catalog").exists()


def test_failed_partition_retains_snapshot_and_later_success_clears_error(
    tmp_path: Path,
) -> None:
    cache = FileHeroGuideCache(tmp_path)
    previous = GuideCacheSnapshot(
        sample_type="pub",
        hero_id=18,
        position=1,
        retrieved_at=_NOW - timedelta(days=1),
        content_type="application/json",
        raw_body=b"old-success",
        source_rows=[],
        pub_guides=[],
    )
    _run(cache.publish(previous, attempted_at=_ATTEMPTED))
    first_client = FakeD2PTClient(
        outcomes={("pub_builds", 18, 1): D2PTTimeoutError()}
    )

    async def no_sleep(_delay: float) -> None:
        return None

    partial = _run(
        HeroGuideRefresher(
            first_client,
            cache,
            clock=lambda: _NOW,
            sleep=no_sleep,
        ).refresh_all()
    )

    failed_entry = _run(cache.get_pub(hero_id=18, position=1))
    assert partial.status == "partial"
    assert partial.request_count == 7
    assert partial.failures[0].error_code == "timeout"
    assert failed_entry.snapshot == previous
    assert failed_entry.last_error == "timeout"
    assert failed_entry.last_attempt_at == _NOW
    assert first_client.calls[-1] == ("pro_builds", 18)

    second_client = FakeD2PTClient()
    recovered = _run(
        HeroGuideRefresher(
            second_client,
            cache,
            clock=lambda: _NOW + timedelta(minutes=1),
            sleep=no_sleep,
        ).refresh_all()
    )
    recovered_entry = _run(cache.get_pub(hero_id=18, position=1))
    assert recovered.status == "success"
    assert recovered_entry.snapshot is not None
    assert recovered_entry.snapshot.raw_body == b"[]"
    assert recovered_entry.last_error is None
    assert recovered_entry.last_attempt_at == _NOW + timedelta(minutes=1)


def test_file_write_failure_aborts_before_next_request(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "guides").write_text("blocks directory creation", encoding="utf-8")
    client = FakeD2PTClient()

    async def no_sleep(_delay: float) -> None:
        return None

    with pytest.raises(HeroGuideCacheUnavailableError):
        _run(
            HeroGuideRefresher(
                client,
                FileHeroGuideCache(data_root),
                clock=lambda: _NOW,
                sleep=no_sleep,
            ).refresh_all()
        )

    assert client.calls == [("heroes_list",), ("pub_builds", 18, 1)]
