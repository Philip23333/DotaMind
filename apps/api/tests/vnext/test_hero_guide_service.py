from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.vnext.capabilities.hero.guide import (
    GuideItemObservation,
    HeroGuideInput,
    ProAbilityEvent,
    ProMatchExample,
    PubGuide,
    SkillSequenceOption,
    StartingItemOption,
    TalentObservation,
)
from app.vnext.capabilities.hero.service import HeroGuideQueryError, HeroGuideService
from app.vnext.hero_guides.cache import (
    GuideCacheEntry,
    GuideCacheSnapshot,
    HeroGuideCacheDataError,
    HeroGuideCacheUnavailableError,
)
from app.vnext.providers.d2pt.parsers import parse_pro_examples, parse_pub_builds

_NOW = datetime(2026, 9, 28, 3, 0, tzinfo=UTC)
_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "d2pt"


class FakeGuideCache:
    def __init__(
        self,
        *,
        pub: GuideCacheEntry | None = None,
        pro: GuideCacheEntry | None = None,
        pub_error: BaseException | None = None,
        pro_error: BaseException | None = None,
    ) -> None:
        self.pub = pub or GuideCacheEntry()
        self.pro = pro or GuideCacheEntry()
        self.pub_error = pub_error
        self.pro_error = pro_error
        self.pub_calls: list[tuple[int, int]] = []
        self.pro_calls: list[int] = []

    async def get_pub(self, *, hero_id: int, position: int) -> GuideCacheEntry:
        self.pub_calls.append((hero_id, position))
        if self.pub_error is not None:
            raise self.pub_error
        return self.pub

    async def get_pro(self, *, hero_id: int) -> GuideCacheEntry:
        self.pro_calls.append(hero_id)
        if self.pro_error is not None:
            raise self.pro_error
        return self.pro


def _run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def _query(section: str = "all") -> HeroGuideInput:
    return HeroGuideInput(hero_id=18, position=1, section=section)


def _pro_example(
    match_id: int,
    *,
    hero_id: int = 18,
    position: int | None = 1,
) -> ProMatchExample:
    return ProMatchExample(
        source_match_id=match_id,
        hero_id=hero_id,
        position=position,
        position_basis="build" if position is not None else "unknown",
        ability_timeline=[ProAbilityEvent(ability_id=1, source_fields={"rank": match_id})],
        source_path=f"$[0].recent_matches[{match_id}]",
    )


def _pub_snapshot(
    *,
    retrieved_at: datetime = _NOW,
    source_rows: list[dict[str, Any]] | None = None,
    guides: list[PubGuide] | None = None,
) -> GuideCacheSnapshot:
    return GuideCacheSnapshot(
        sample_type="pub",
        hero_id=18,
        position=1,
        retrieved_at=retrieved_at,
        content_type="application/json",
        raw_body=b"pub-source-bytes",
        source_rows=[] if source_rows is None else source_rows,
        pub_guides=[] if guides is None else guides,
    )


def _pro_snapshot(
    *,
    retrieved_at: datetime = _NOW,
    source_rows: list[dict[str, Any]] | None = None,
    examples: list[ProMatchExample] | None = None,
) -> GuideCacheSnapshot:
    return GuideCacheSnapshot(
        sample_type="pro",
        hero_id=18,
        position=None,
        retrieved_at=retrieved_at,
        content_type="application/json",
        raw_body=b"pro-source-bytes",
        source_rows=[] if source_rows is None else source_rows,
        pro_examples=[] if examples is None else examples,
    )


def _fixture_entries() -> tuple[GuideCacheEntry, GuideCacheEntry]:
    pub_raw = (_FIXTURE_DIR / "pub_sven_pos1.json").read_bytes()
    pub_rows = json.loads(pub_raw)
    pub = _pub_snapshot(
        source_rows=pub_rows,
        guides=parse_pub_builds(pub_rows, hero_id=18, position=1),
    ).model_copy(update={"raw_body": pub_raw})
    pro_raw = (_FIXTURE_DIR / "pro_sven.json").read_bytes()
    pro_rows = json.loads(pro_raw)
    pro = _pro_snapshot(
        source_rows=pro_rows,
        examples=parse_pro_examples(pro_rows, hero_id=18),
    ).model_copy(update={"raw_body": pro_raw})
    return (
        GuideCacheEntry(snapshot=pub, last_attempt_at=_NOW),
        GuideCacheEntry(snapshot=pro, last_attempt_at=_NOW),
    )


def test_fixture_query_reads_both_sources_once_and_filters_pro_position() -> None:
    pub_entry, pro_entry = _fixture_entries()
    cache = FakeGuideCache(pub=pub_entry, pro=pro_entry)
    clock_calls: list[datetime] = []

    result = _run(
        HeroGuideService(cache, clock=lambda: clock_calls.append(_NOW) or _NOW).get_guide(
            _query()
        )
    )

    assert result.pub_guides == pub_entry.snapshot.pub_guides
    assert result.pro_examples == [
        example
        for example in pro_entry.snapshot.pro_examples
        if example.hero_id == 18 and example.position == 1
    ]
    assert result.pub_metadata.availability == "available"
    assert result.pro_metadata.availability == (
        "available" if result.pro_examples else "empty"
    )
    assert result.pub_guides_total == len(pub_entry.snapshot.pub_guides)
    assert result.pro_examples_total == len(result.pro_examples)
    assert cache.pub_calls == [(18, 1)]
    assert cache.pro_calls == [18]
    assert clock_calls == [_NOW]
    assert not hasattr(cache, "publish")
    assert not hasattr(cache, "record_failure")


def test_pro_filter_preserves_source_order_and_duplicates_and_excludes_unknown_position() -> None:
    examples = [
        _pro_example(1),
        _pro_example(2, position=2),
        _pro_example(1),
        _pro_example(3, position=None),
        _pro_example(4, hero_id=19),
    ]
    cache = FakeGuideCache(pro=GuideCacheEntry(snapshot=_pro_snapshot(examples=examples)))

    result = _run(HeroGuideService(cache, clock=lambda: _NOW).get_guide(_query()))

    assert [example.source_match_id for example in result.pro_examples] == [1, 1]
    assert result.pro_examples_total == 2


def _complete_pub_guide() -> PubGuide:
    return PubGuide(
        build_id=9,
        facet_id=4,
        source_updated_at="source-time",
        scope={"position": "pos 1"},
        statistics={"num_matches": 100},
        starting_options=[StartingItemOption(source_path="$.starting_items_new[0]")],
        item_progression=[GuideItemObservation(item_id=1, phase="mid", source_path="$.items[0]")],
        situational_items=[
            GuideItemObservation(item_id=2, phase="late", source_path="$.items[1]")
        ],
        skill_sequences=[SkillSequenceOption(ability_ids=[1, 2], source_path="$.abilities[0]")],
        talents=[TalentObservation(level=10, source_path="$.talents[0]")],
    )


@pytest.mark.parametrize("section", ["all", "items", "skills", "pro_examples"])
def test_sections_project_fields_without_changing_source_status_or_totals(section: str) -> None:
    guide = _complete_pub_guide()
    examples = [_pro_example(1)]
    cache = FakeGuideCache(
        pub=GuideCacheEntry(snapshot=_pub_snapshot(guides=[guide])),
        pro=GuideCacheEntry(snapshot=_pro_snapshot(examples=examples)),
    )

    result = _run(HeroGuideService(cache, clock=lambda: _NOW).get_guide(_query(section)))

    assert result.section == section
    assert result.pub_metadata.availability == "available"
    assert result.pro_metadata.availability == "available"
    assert result.pub_guides_total == 1
    assert result.pro_examples_total == 1
    assert cache.pub_calls == [(18, 1)]
    assert cache.pro_calls == [18]
    if section in {"all", "skills"}:
        assert len(result.pub_guides) == 1
        assert result.pub_guides[0].skill_sequences
        assert result.pub_guides[0].talents
    elif section == "pro_examples":
        assert result.pub_guides == []
    else:
        assert len(result.pub_guides) == 1
    if section == "items":
        projected = result.pub_guides[0]
        assert projected.starting_options
        assert projected.item_progression
        assert projected.situational_items
        assert projected.skill_sequences == []
        assert projected.talents == []
        assert result.pro_examples == []
    elif section == "skills":
        projected = result.pub_guides[0]
        assert projected.starting_options == []
        assert projected.item_progression == []
        assert projected.situational_items == []
        assert result.pro_examples == []
    elif section == "pro_examples":
        assert result.pub_guides == []
        assert result.pro_examples == examples
    else:
        assert result.pub_guides[0] == guide
        assert result.pro_examples == examples


def test_projection_keeps_pub_rows_that_become_empty() -> None:
    guide = PubGuide(skill_sequences=[SkillSequenceOption(source_path="$.skills")])
    cache = FakeGuideCache(pub=GuideCacheEntry(snapshot=_pub_snapshot(guides=[guide])))

    result = _run(HeroGuideService(cache, clock=lambda: _NOW).get_guide(_query("items")))

    assert len(result.pub_guides) == 1
    assert result.pub_guides[0].skill_sequences == []
    assert result.pub_guides_total == 1


@pytest.mark.parametrize(
    ("age", "expected_stale"),
    [
        (timedelta(hours=35, minutes=59), False),
        (timedelta(hours=36), True),
        (timedelta(hours=36, seconds=1), True),
        (timedelta(hours=-1), False),
    ],
)
def test_snapshot_freshness_boundary_and_future_time(age: timedelta, expected_stale: bool) -> None:
    snapshot = _pub_snapshot(retrieved_at=_NOW - age, guides=[PubGuide(build_id=2)])
    cache = FakeGuideCache(pub=GuideCacheEntry(snapshot=snapshot))

    result = _run(HeroGuideService(cache, clock=lambda: _NOW).get_guide(_query()))

    assert result.pub_metadata.stale is expected_stale


def test_empty_snapshot_can_be_stale_and_other_position_pro_means_empty() -> None:
    cache = FakeGuideCache(
        pub=GuideCacheEntry(
            snapshot=_pub_snapshot(retrieved_at=_NOW - timedelta(hours=37))
        ),
        pro=GuideCacheEntry(
            snapshot=_pro_snapshot(examples=[_pro_example(8, position=2)])
        ),
    )

    result = _run(HeroGuideService(cache, clock=lambda: _NOW).get_guide(_query()))

    assert result.pub_metadata.availability == "empty"
    assert result.pub_metadata.stale is True
    assert result.pub_guides_total == 0
    assert result.pro_metadata.availability == "empty"
    assert result.pro_examples == []
    assert result.pro_examples_total == 0


def test_old_snapshot_after_refresh_failure_remains_available_and_stale() -> None:
    entry = GuideCacheEntry(
        snapshot=_pub_snapshot(guides=[PubGuide(build_id=7)]),
        last_attempt_at=_NOW + timedelta(minutes=1),
        last_error="timeout",
    )
    result = _run(
        HeroGuideService(FakeGuideCache(pub=entry), clock=lambda: _NOW).get_guide(_query())
    )

    assert result.pub_metadata.availability == "available"
    assert result.pub_metadata.stale is True
    assert result.pub_metadata.last_error == "timeout"
    assert result.pub_metadata.last_attempt_at == _NOW + timedelta(minutes=1)
    assert result.pub_guides_total == 1


def test_future_snapshot_after_refresh_failure_is_still_stale() -> None:
    entry = GuideCacheEntry(
        snapshot=_pub_snapshot(retrieved_at=_NOW + timedelta(days=2), guides=[PubGuide()]),
        last_attempt_at=_NOW,
        last_error="timeout",
    )

    result = _run(
        HeroGuideService(FakeGuideCache(pub=entry), clock=lambda: _NOW).get_guide(_query())
    )

    assert result.pub_metadata.stale is True


def test_first_refresh_failure_and_cache_miss_are_missing_with_attempt_state() -> None:
    cache = FakeGuideCache(
        pub=GuideCacheEntry(last_attempt_at=_NOW, last_error="http_error")
    )

    result = _run(HeroGuideService(cache, clock=lambda: _NOW).get_guide(_query()))

    assert result.pub_metadata.availability == "missing"
    assert result.pub_metadata.stale is False
    assert result.pub_metadata.retrieved_at is None
    assert result.pub_metadata.last_attempt_at == _NOW
    assert result.pub_metadata.last_error == "http_error"
    assert result.pub_guides_total is None
    assert result.pro_metadata.availability == "missing"
    assert result.pro_examples_total is None


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([{"updated_at": "7.41f"}], "7.41f"),
        ([{"updated_at": "7.41f"}, {"updated_at": "7.41f"}], "7.41f"),
        ([{"updated_at": "7.41f"}, {"updated_at": "7.41g"}], None),
        ([{"position": "pos 1"}], None),
        ([{"updated_at": None}], None),
        ([{"updated_at": ""}], None),
    ],
)
def test_source_updated_at_requires_identical_nonempty_strings(
    rows: list[dict[str, Any]], expected: str | None
) -> None:
    cache = FakeGuideCache(pub=GuideCacheEntry(snapshot=_pub_snapshot(source_rows=rows)))

    result = _run(HeroGuideService(cache, clock=lambda: _NOW).get_guide(_query()))

    assert result.pub_metadata.source_updated_at == expected


def test_scope_copies_only_source_scope_fields_and_preserves_nulls() -> None:
    rows = [
        {
            "position": "pos 1",
            "updated_at": "7.41f",
            "data_scope": {"window": None, "version": "7.41f"},
            "other": "not copied",
        },
        {"position": None, "data_scope": None},
    ]
    cache = FakeGuideCache(pub=GuideCacheEntry(snapshot=_pub_snapshot(source_rows=rows)))
    original = json.loads(json.dumps(rows))

    first = _run(HeroGuideService(cache, clock=lambda: _NOW).get_guide(_query()))
    first.pub_metadata.scope["records"][0]["data_scope"]["window"] = "mutated"
    second = _run(HeroGuideService(cache, clock=lambda: _NOW).get_guide(_query()))

    assert rows == original
    assert second.pub_metadata.scope == {
        "records": [
            {
                "source_path": "$[0]",
                "position": "pos 1",
                "updated_at": "7.41f",
                "data_scope": {"window": None, "version": "7.41f"},
            },
            {"source_path": "$[1]", "position": None, "data_scope": None},
        ]
    }
    assert "other" not in json.dumps(second.pub_metadata.scope)


@pytest.mark.parametrize(
    ("failed_source", "error_type", "error_code"),
    [
        ("pub", HeroGuideCacheUnavailableError, "cache_unavailable"),
        ("pub", HeroGuideCacheDataError, "cache_invalid_data"),
        ("pro", HeroGuideCacheUnavailableError, "cache_unavailable"),
        ("pro", HeroGuideCacheDataError, "cache_invalid_data"),
    ],
)
def test_single_cache_read_error_returns_other_source_and_fixed_metadata(
    failed_source: str,
    error_type: type[Exception],
    error_code: str,
) -> None:
    pub_entry, pro_entry = _fixture_entries()
    kwargs: dict[str, Any] = {
        "pub": pub_entry,
        "pro": pro_entry,
        "pub_error": error_type() if failed_source == "pub" else None,
        "pro_error": error_type() if failed_source == "pro" else None,
    }
    cache = FakeGuideCache(**kwargs)

    result = _run(HeroGuideService(cache, clock=lambda: _NOW).get_guide(_query()))

    failed_metadata = result.pub_metadata if failed_source == "pub" else result.pro_metadata
    successful_metadata = result.pro_metadata if failed_source == "pub" else result.pub_metadata
    assert failed_metadata.availability == "missing"
    assert failed_metadata.stale is False
    assert failed_metadata.retrieved_at is None
    assert failed_metadata.last_attempt_at is None
    assert failed_metadata.last_error == error_code
    assert successful_metadata.availability in {"available", "empty"}
    assert cache.pub_calls == [(18, 1)]
    assert cache.pro_calls == [18]
    if failed_source == "pub":
        assert result.pub_guides == []
        assert result.pub_guides_total is None
        assert result.pro_examples_total is not None
    else:
        assert result.pro_examples == []
        assert result.pro_examples_total is None
        assert result.pub_guides_total is not None
    assert "CACHE_PRIVATE_SECRET" not in result.model_dump_json()


def test_both_cache_read_errors_raise_fixed_query_error() -> None:
    cache = FakeGuideCache(
        pub_error=HeroGuideCacheUnavailableError(),
        pro_error=HeroGuideCacheDataError(),
    )

    with pytest.raises(HeroGuideQueryError) as exc_info:
        _run(HeroGuideService(cache, clock=lambda: _NOW).get_guide(_query()))

    assert str(exc_info.value) == "hero guide cache could not be read"
    assert exc_info.value.pub_error == "cache_unavailable"
    assert exc_info.value.pro_error == "cache_invalid_data"
    assert cache.pub_calls == [(18, 1)]
    assert cache.pro_calls == [18]


def test_two_cache_misses_are_a_normal_result_not_a_query_error() -> None:
    result = _run(HeroGuideService(FakeGuideCache(), clock=lambda: _NOW).get_guide(_query()))

    assert result.pub_metadata.availability == "missing"
    assert result.pro_metadata.availability == "missing"
    assert result.pub_guides == []
    assert result.pro_examples == []
    assert result.pub_guides_total is None
    assert result.pro_examples_total is None


def test_cancellation_and_unexpected_cache_errors_are_not_converted() -> None:
    cancelled = FakeGuideCache(pub_error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        _run(HeroGuideService(cancelled, clock=lambda: _NOW).get_guide(_query()))
    assert cancelled.pro_calls == []

    unexpected = FakeGuideCache(pub_error=RuntimeError("unexpected"))
    with pytest.raises(RuntimeError, match="unexpected"):
        _run(HeroGuideService(unexpected, clock=lambda: _NOW).get_guide(_query()))


@pytest.mark.parametrize("value", [timedelta(0), timedelta(seconds=-1)])
def test_stale_after_must_be_positive(value: timedelta) -> None:
    with pytest.raises(ValueError, match="stale_after"):
        HeroGuideService(FakeGuideCache(), stale_after=value)


def test_clock_is_called_once_and_must_return_timezone_aware_time() -> None:
    calls = 0

    def clock() -> datetime:
        nonlocal calls
        calls += 1
        return datetime(2026, 9, 28)

    with pytest.raises(ValueError, match="timezone-aware"):
        _run(HeroGuideService(FakeGuideCache(), clock=clock).get_guide(_query()))
    assert calls == 1


def test_mutating_service_output_does_not_mutate_cache_entries() -> None:
    guide = PubGuide(statistics={"counts": {"wins": 4}})
    example = _pro_example(9)
    cache = FakeGuideCache(
        pub=GuideCacheEntry(snapshot=_pub_snapshot(guides=[guide])),
        pro=GuideCacheEntry(snapshot=_pro_snapshot(examples=[example])),
    )

    first = _run(HeroGuideService(cache, clock=lambda: _NOW).get_guide(_query()))
    first.pub_guides[0].statistics["counts"]["wins"] = 0
    first.pro_examples[0].ability_timeline[0].source_fields["rank"] = 0
    second = _run(HeroGuideService(cache, clock=lambda: _NOW).get_guide(_query()))

    assert second.pub_guides[0].statistics["counts"]["wins"] == 4
    assert second.pro_examples[0].ability_timeline[0].source_fields["rank"] == 9
