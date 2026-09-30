"""Read-only query service for cached hero guide source snapshots."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import JsonValue

from app.vnext.capabilities.hero.enrichment import enrich_hero_guide
from app.vnext.capabilities.hero.guide import (
    GuideSourceMetadata,
    HeroGuideInput,
    HeroGuideResult,
    ProMatchExample,
    PubGuide,
)
from app.vnext.catalog import EntityNameResolver
from app.vnext.hero_guides.cache import (
    GuideCacheEntry,
    GuideCacheSnapshot,
    HeroGuideCacheDataError,
    HeroGuideCacheUnavailableError,
    HeroGuideReader,
)

_SCOPE_FIELDS = ("position", "updated_at", "data_scope")


class HeroGuideQueryError(RuntimeError):
    """Both source cache reads failed with fixed, non-sensitive error codes."""

    def __init__(self, *, pub_error: str, pro_error: str) -> None:
        super().__init__("hero guide cache could not be read")
        self.pub_error = pub_error
        self.pro_error = pro_error


class HeroGuideService:
    """Combine cached Pub and Pro snapshots for one hero-position query."""

    def __init__(
        self,
        cache: HeroGuideReader,
        resolver_factory: Callable[[], EntityNameResolver],
        *,
        clock: Callable[[], datetime] | None = None,
        stale_after: timedelta = timedelta(hours=36),
    ) -> None:
        if stale_after <= timedelta(0):
            raise ValueError("stale_after must be greater than zero")
        self._cache = cache
        self._resolver_factory = resolver_factory
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)
        self._stale_after = stale_after

    async def get_guide(self, query: HeroGuideInput) -> HeroGuideResult:
        resolver = self._resolver_factory()
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")

        pub_entry: GuideCacheEntry | None = None
        pro_entry: GuideCacheEntry | None = None
        pub_error: str | None = None
        pro_error: str | None = None

        try:
            pub_entry = await self._cache.get_pub(
                hero_id=query.hero_id,
                position=query.position,
            )
        except (HeroGuideCacheUnavailableError, HeroGuideCacheDataError) as exc:
            pub_error = _cache_error_code(exc)

        try:
            pro_entry = await self._cache.get_pro(hero_id=query.hero_id)
        except (HeroGuideCacheUnavailableError, HeroGuideCacheDataError) as exc:
            pro_error = _cache_error_code(exc)

        if pub_error is not None and pro_error is not None:
            raise HeroGuideQueryError(pub_error=pub_error, pro_error=pro_error) from None

        all_pub_guides = (
            list(pub_entry.snapshot.pub_guides)
            if pub_entry is not None and pub_entry.snapshot is not None
            else []
        )
        all_pro_examples = _examples_for_position(
            pro_entry.snapshot if pro_entry is not None else None,
            hero_id=query.hero_id,
            position=query.position,
        )

        pub_metadata = _source_metadata(
            sample_type="pub",
            entry=pub_entry,
            read_error=pub_error,
            candidate_count=len(all_pub_guides),
            now=now,
            stale_after=self._stale_after,
        )
        pro_metadata = _source_metadata(
            sample_type="pro",
            entry=pro_entry,
            read_error=pro_error,
            candidate_count=len(all_pro_examples),
            now=now,
            stale_after=self._stale_after,
        )

        pub_guides, pro_examples = _project_section(
            all_pub_guides,
            all_pro_examples,
            query.section,
        )
        result = HeroGuideResult(
            hero_id=query.hero_id,
            position=query.position,
            section=query.section,
            pub_metadata=pub_metadata,
            pro_metadata=pro_metadata,
            pub_guides=pub_guides,
            pro_examples=pro_examples,
            pub_guides_total=(
                len(all_pub_guides)
                if pub_entry is not None and pub_entry.snapshot is not None
                else None
            ),
            pro_examples_total=(
                len(all_pro_examples)
                if pro_entry is not None and pro_entry.snapshot is not None
                else None
            ),
        )
        return enrich_hero_guide(result, resolver)


def _cache_error_code(
    error: HeroGuideCacheUnavailableError | HeroGuideCacheDataError,
) -> Literal["cache_unavailable", "cache_invalid_data"]:
    if isinstance(error, HeroGuideCacheUnavailableError):
        return "cache_unavailable"
    return "cache_invalid_data"


def _examples_for_position(
    snapshot: GuideCacheSnapshot | None,
    *,
    hero_id: int,
    position: int,
) -> list[ProMatchExample]:
    if snapshot is None:
        return []
    return [
        example
        for example in snapshot.pro_examples
        if example.hero_id == hero_id and example.position == position
    ]


def _source_metadata(
    *,
    sample_type: Literal["pub", "pro"],
    entry: GuideCacheEntry | None,
    read_error: str | None,
    candidate_count: int,
    now: datetime,
    stale_after: timedelta,
) -> GuideSourceMetadata:
    if read_error is not None:
        return GuideSourceMetadata(
            provider="d2pt",
            sample_type=sample_type,
            availability="missing",
            stale=False,
            last_error=read_error,
        )

    if entry is None or entry.snapshot is None:
        return GuideSourceMetadata(
            provider="d2pt",
            sample_type=sample_type,
            availability="missing",
            stale=False,
            last_attempt_at=entry.last_attempt_at if entry is not None else None,
            last_error=entry.last_error if entry is not None else None,
        )

    snapshot = entry.snapshot
    stale = entry.last_error is not None or now - snapshot.retrieved_at >= stale_after
    return GuideSourceMetadata(
        provider="d2pt",
        sample_type=sample_type,
        availability="available" if candidate_count else "empty",
        stale=stale,
        retrieved_at=snapshot.retrieved_at,
        source_updated_at=_source_updated_at(snapshot.source_rows),
        last_attempt_at=entry.last_attempt_at,
        last_error=entry.last_error,
        scope=_source_scope(snapshot.source_rows),
    )


def _source_updated_at(source_rows: list[dict[str, JsonValue]]) -> str | None:
    if not source_rows:
        return None
    values = [row.get("updated_at") for row in source_rows]
    if any(not isinstance(value, str) or not value for value in values):
        return None
    first = values[0]
    return first if all(value == first for value in values) else None


def _source_scope(source_rows: list[dict[str, JsonValue]]) -> dict[str, JsonValue]:
    if not source_rows:
        return {}
    records: list[dict[str, JsonValue]] = []
    for index, row in enumerate(source_rows):
        record: dict[str, JsonValue] = {"source_path": f"$[{index}]"}
        for key in _SCOPE_FIELDS:
            if key in row:
                record[key] = deepcopy(row[key])
        records.append(record)
    return {"records": records}


def _project_section(
    pub_guides: list[PubGuide],
    pro_examples: list[ProMatchExample],
    section: Literal["all", "items", "skills", "pro_examples"],
) -> tuple[list[PubGuide], list[ProMatchExample]]:
    if section == "all":
        return (
            [guide.model_copy(deep=True) for guide in pub_guides],
            [example.model_copy(deep=True) for example in pro_examples],
        )
    if section == "items":
        return (
            [
                guide.model_copy(
                    deep=True,
                    update={"skill_sequences": [], "talents": []},
                )
                for guide in pub_guides
            ],
            [],
        )
    if section == "skills":
        return (
            [
                guide.model_copy(
                    deep=True,
                    update={
                        "starting_options": [],
                        "item_progression": [],
                        "situational_items": [],
                    },
                )
                for guide in pub_guides
            ],
            [],
        )
    return [], [example.model_copy(deep=True) for example in pro_examples]


__all__ = ["HeroGuideQueryError", "HeroGuideService"]
