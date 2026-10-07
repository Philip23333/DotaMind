"""Cached homepage candidates assembled from PandaScore Series lifecycles."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from redis.exceptions import RedisError

from app.vnext.capabilities.esports.team import TeamSearchInput, TeamSearchResult
from app.vnext.providers.pandascore.client import (
    PandaScoreConfigurationError,
    PandaScoreProtocolError,
)
from app.vnext.providers.pandascore.series_lifecycle import (
    SeriesLifecycleItem,
    SeriesLifecycleResult,
)
from app.vnext.providers.pandascore.tournament_winners import TournamentWinnerSource

logger = logging.getLogger(__name__)

_CACHE_KEY = "dotamind:vnext:homepage:recent-series:v1"
_CACHE_FIELDS = {
    "snapshot",
    "last_attempt_at",
    "last_error",
    "manual_refresh_available_at",
}
_REFRESH_SECONDS = 600
_MANUAL_REFRESH_COOLDOWN_SECONDS = 60
_HOMEPAGE_REFRESH_CONCURRENCY = 6
_CANDIDATE_LIMIT = 10
_PROVIDER_PAGE_LIMIT = 100
_ERROR_CODES = {
    "configuration_error",
    "http_error",
    "transport_error",
    "timeout",
    "invalid_response",
    "cache_unavailable",
}
_ProviderError = (
    PandaScoreConfigurationError,
    PandaScoreProtocolError,
    httpx.HTTPError,
    json.JSONDecodeError,
    UnicodeDecodeError,
)
_OPTIONAL_TEAM_ERRORS = (*_ProviderError, ValueError)
_T = TypeVar("_T")


class RecentSeriesCandidate(BaseModel):
    """A bounded, display-ready Series candidate."""

    model_config = ConfigDict(extra="forbid")

    series_id: int
    name: str | None
    league_name: str | None = None
    lifecycle: Literal["running", "past"]
    begin_at: datetime | None = None
    end_at: datetime | None = None
    champion_name: str | None = None
    champion_source: Literal["series", "tournament"] | None = None
    champion_tournament_id: int | None = None


class RecentSeriesSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RecentSeriesCandidate]
    retrieved_at: datetime

    @field_validator("retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value


class RecentSeriesCacheEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: RecentSeriesSnapshot | None = None
    last_attempt_at: datetime | None = None
    last_error: str | None = None
    manual_refresh_available_at: datetime | None = None

    @field_validator("last_attempt_at")
    @classmethod
    def require_attempt_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("last_attempt_at must include a timezone")
        return value

    @field_validator("manual_refresh_available_at")
    @classmethod
    def require_manual_refresh_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("manual_refresh_available_at must include a timezone")
        return value


class RecentSeriesResponse(BaseModel):
    """Data and refresh state for the homepage and its expanded candidate list."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["fresh", "stale", "unavailable"]
    items: list[RecentSeriesCandidate]
    retrieved_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_error: str | None = None
    server_time: datetime
    manual_refresh_available_at: datetime | None = None

    @field_validator("server_time", "manual_refresh_available_at")
    @classmethod
    def require_response_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("response timestamps must include a timezone")
        return value


class RecentSeriesCacheUnavailableError(RuntimeError):
    """Raised when the shared Redis cache cannot be read or written."""


class RecentSeriesCacheDataError(RuntimeError):
    """Raised when a stored homepage snapshot is malformed."""


class LifecycleSeriesReader(Protocol):
    async def __call__(
        self,
        *,
        lifecycle: Literal["running", "past"],
        page: int = 1,
        limit: int = 100,
    ) -> SeriesLifecycleResult: ...


class TeamSearcher(Protocol):
    async def __call__(self, query: TeamSearchInput) -> TeamSearchResult: ...


class TournamentWinnerSourceReader(Protocol):
    async def __call__(self, *, series_id: int) -> list[TournamentWinnerSource]: ...


class RecentSeriesCache(Protocol):
    async def get(self) -> RecentSeriesCacheEntry: ...

    async def publish(self, snapshot: RecentSeriesSnapshot, *, attempted_at: datetime) -> None: ...

    async def record_failure(self, *, attempted_at: datetime, error_code: str) -> None: ...

    async def set_manual_refresh_available_at(self, value: datetime) -> None: ...


class RedisRecentSeriesCache:
    """Shared cache retaining the last good snapshot across failed refreshes."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def get(self) -> RecentSeriesCacheEntry:
        try:
            raw_hash = await self._client.hgetall(_CACHE_KEY)
        except RedisError:
            raise RecentSeriesCacheUnavailableError(
                "recent Series cache is temporarily unavailable"
            ) from None
        return _decode_entry(raw_hash)

    async def publish(
        self,
        snapshot: RecentSeriesSnapshot,
        *,
        attempted_at: datetime,
    ) -> None:
        _validate_aware_datetime(attempted_at)
        try:
            checked_snapshot = RecentSeriesSnapshot.model_validate(snapshot)
            snapshot_json = checked_snapshot.model_dump_json()
        except (ValidationError, TypeError, ValueError):
            raise RecentSeriesCacheDataError("recent Series snapshot is invalid") from None
        await self._hset(
            {
                "snapshot": snapshot_json,
                "last_attempt_at": attempted_at.isoformat(),
                "last_error": "",
            }
        )

    async def record_failure(self, *, attempted_at: datetime, error_code: str) -> None:
        _validate_aware_datetime(attempted_at)
        if error_code not in _ERROR_CODES:
            raise ValueError("unsupported recent Series refresh error code")
        await self._hset(
            {
                "last_attempt_at": attempted_at.isoformat(),
                "last_error": error_code,
            }
        )

    async def set_manual_refresh_available_at(self, value: datetime) -> None:
        _validate_aware_datetime(value)
        # Update only cooldown metadata so a concurrent snapshot publication is
        # never replaced with an older cache entry.
        await self._hset({"manual_refresh_available_at": value.isoformat()})

    async def _hset(self, mapping: dict[str, str]) -> None:
        try:
            await self._client.hset(_CACHE_KEY, mapping=mapping)
        except RedisError:
            raise RecentSeriesCacheUnavailableError(
                "recent Series cache is temporarily unavailable"
            ) from None


class HomepageRecentSeriesService:
    """Combines lifecycle reads, resolves explicit Team winners, and caches ten rows."""

    def __init__(
        self,
        *,
        read_lifecycle: LifecycleSeriesReader,
        search_team: TeamSearcher,
        list_tournament_winner_sources: TournamentWinnerSourceReader,
        cache: RecentSeriesCache,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._read_lifecycle = read_lifecycle
        self._search_team = search_team
        self._list_tournament_winner_sources = list_tournament_winner_sources
        self._cache = cache
        self._now = now or _utc_now
        self._refresh_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[RecentSeriesResponse] | None = None
        self._refresh_started_at: datetime | None = None
        self._local_failure: tuple[datetime, str] | None = None
        self._closed = False

    async def get_recent_series(self) -> RecentSeriesResponse:
        requested_at = _ensure_aware(self._now())
        entry = await self._cache.get()
        if _is_fresh(entry.snapshot, requested_at):
            return self._entry_response(entry, status="fresh")

        async with self._refresh_lock:
            # Recheck the shared snapshot after acquiring the short state lock.
            # A refresh may have completed since the first cache read.
            entry = await self._cache.get()
            now = _ensure_aware(self._now())
            if _is_fresh(entry.snapshot, now):
                return self._entry_response(entry, status="fresh")
            if self._closed:
                return self._entry_response(
                    entry,
                    status="stale" if entry.snapshot is not None else "unavailable",
                )

            task = self._refresh_task
            if task is not None and task.done():
                self._refresh_task = None
                self._refresh_started_at = None
                task = None
            if task is None and _failure_cooldown_active(
                entry,
                now,
                local_failure=self._local_failure,
            ):
                return self._entry_response(
                    entry,
                    status="stale" if entry.snapshot is not None else "unavailable",
                )
            if task is None:
                self._refresh_started_at = now
                task = asyncio.create_task(self._refresh(entry))
                self._refresh_task = task
                task.add_done_callback(self._consume_refresh_result)

        if entry.snapshot is not None:
            # Stale snapshots are useful immediately. The owned task continues
            # in the background and later requests will observe its result.
            return self._entry_response(entry, status="stale")

        # Cold-cache callers share the service-owned refresh and cannot cancel it.
        return await asyncio.shield(task)

    async def refresh_recent_series(self) -> RecentSeriesResponse:
        async with self._refresh_lock:
            now = _ensure_aware(self._now())
            if self._closed:
                entry = await self._cache.get()
                return self._entry_response(
                    entry,
                    status=_entry_status(entry, now),
                )

            task = self._refresh_task
            if task is not None and task.done():
                self._refresh_task = None
                self._refresh_started_at = None
                task = None

            entry = await self._cache.get()
            now = _ensure_aware(self._now())
            if task is None:
                available_at = _manual_refresh_available_at(
                    entry,
                    now,
                    local_failure=self._local_failure,
                )
                if available_at is not None:
                    return self._entry_response(
                        entry,
                        status=_entry_status(entry, now),
                    )
                started_at = now
            else:
                # A manual request joining an automatic refresh uses the
                # original task start; additional waiters do not extend it.
                started_at = self._refresh_started_at or now

            manual_available_at = started_at + timedelta(
                seconds=_MANUAL_REFRESH_COOLDOWN_SECONDS
            )
            if (
                entry.manual_refresh_available_at is None
                or entry.manual_refresh_available_at < manual_available_at
            ):
                await self._cache.set_manual_refresh_available_at(manual_available_at)
            if task is None:
                self._refresh_started_at = started_at
                task = asyncio.create_task(self._refresh(entry))
                self._refresh_task = task
                task.add_done_callback(self._consume_refresh_result)

        # The cache mutation and lock are complete before waiting; cancellation
        # of this request cannot cancel the service-owned refresh task.
        refresh_result = await asyncio.shield(task)
        refreshed_entry = await self._cache.get()
        return self._entry_response(refreshed_entry, status=refresh_result.status)

    async def aclose(self) -> None:
        async with self._refresh_lock:
            self._closed = True
            task = self._refresh_task
            if task is not None and not task.done():
                task.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def _refresh(self, previous_entry: RecentSeriesCacheEntry) -> RecentSeriesResponse:
        current_task = asyncio.current_task()
        try:
            return await self._perform_refresh(previous_entry)
        finally:
            if self._refresh_task is current_task:
                self._refresh_task = None
                self._refresh_started_at = None

    async def _perform_refresh(
        self,
        previous_entry: RecentSeriesCacheEntry,
    ) -> RecentSeriesResponse:
        try:
            items = await self._load_candidates()
        except _ProviderError as exc:
            error_code = _provider_error_code(exc)
            attempted_at = _ensure_aware(self._now())
            logger.warning("Homepage Series refresh failed: code=%s", error_code)
            try:
                await self._cache.record_failure(
                    attempted_at=attempted_at,
                    error_code=error_code,
                )
            except RecentSeriesCacheUnavailableError:
                self._local_failure = (attempted_at, error_code)
                if previous_entry.snapshot is None:
                    return self._entry_response(
                        previous_entry,
                        status="unavailable",
                        last_attempt_at=attempted_at,
                        last_error=error_code,
                    )
                return self._entry_response(
                    previous_entry,
                    status=_entry_status(previous_entry, attempted_at),
                    last_attempt_at=attempted_at,
                    last_error=error_code,
                )
            failed_entry = await self._cache.get()
            return self._entry_response(
                failed_entry,
                status=_entry_status(failed_entry, _ensure_aware(self._now())),
            )

        retrieved_at = _ensure_aware(self._now())
        snapshot = RecentSeriesSnapshot(items=items, retrieved_at=retrieved_at)
        try:
            await self._cache.publish(snapshot, attempted_at=retrieved_at)
        except RecentSeriesCacheUnavailableError:
            self._local_failure = (retrieved_at, "cache_unavailable")
            if previous_entry.snapshot is None:
                return self._entry_response(
                    previous_entry,
                    status="unavailable",
                    last_attempt_at=retrieved_at,
                    last_error="cache_unavailable",
                )
            return self._entry_response(
                previous_entry,
                status=_entry_status(previous_entry, retrieved_at),
                last_attempt_at=retrieved_at,
                last_error="cache_unavailable",
            )
        self._local_failure = None
        published_entry = await self._cache.get()
        return self._entry_response(published_entry, status="fresh")

    def _entry_response(
        self,
        entry: RecentSeriesCacheEntry,
        *,
        status: Literal["fresh", "stale", "unavailable"],
        last_attempt_at: datetime | None = None,
        last_error: str | None = None,
    ) -> RecentSeriesResponse:
        now = _ensure_aware(self._now())
        local_failure = self._local_failure
        if (
            local_failure is not None
            and (entry.last_attempt_at is None or local_failure[0] >= entry.last_attempt_at)
        ):
            last_attempt_at = local_failure[0]
            last_error = local_failure[1]
        return _response(
            entry,
            status=status,
            server_time=now,
            manual_refresh_available_at=_manual_refresh_available_at(
                entry,
                now,
                local_failure=local_failure,
            ),
            last_attempt_at=last_attempt_at,
            last_error=last_error,
        )

    @staticmethod
    def _consume_refresh_result(task: asyncio.Task[RecentSeriesResponse]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            # Avoid leaking provider details and ensure background exceptions are
            # always retrieved even when no cold-start request is awaiting them.
            logger.error(
                "Homepage Series refresh crashed: error_type=%s",
                type(error).__name__,
            )

    async def _load_candidates(self) -> list[RecentSeriesCandidate]:
        semaphore = asyncio.Semaphore(_HOMEPAGE_REFRESH_CONCURRENCY)

        async def read_lifecycle(
            lifecycle: Literal["running", "past"],
        ) -> SeriesLifecycleResult:
            async with semaphore:
                return await self._read_lifecycle(
                    lifecycle=lifecycle,
                    page=1,
                    limit=_PROVIDER_PAGE_LIMIT,
                )

        async def list_tournament_winner_sources(
            *, series_id: int,
        ) -> list[TournamentWinnerSource]:
            async with semaphore:
                return await self._list_tournament_winner_sources(series_id=series_id)

        lifecycle_tasks = [
            asyncio.create_task(read_lifecycle(lifecycle))
            for lifecycle in ("running", "past")
        ]
        candidate_tasks: list[asyncio.Task[RecentSeriesCandidate]] = []
        team_tasks: dict[int, asyncio.Task[str | None]] = {}

        async def team_name(team_id: int) -> str | None:
            task = team_tasks.get(team_id)
            if task is None:
                task = asyncio.create_task(self._resolve_team_name(team_id, semaphore))
                team_tasks[team_id] = task
            # Candidate cancellation must not cancel a lookup shared by other
            # candidates; the refresh owns and reaps these tasks below.
            return await asyncio.shield(task)

        try:
            running, past = await _gather_ordered(lifecycle_tasks)
            _require_mappable_response(running)
            _require_mappable_response(past)

            selected = _select_candidates(running.items, past.items)
            candidate_tasks = [
                asyncio.create_task(
                    self._build_candidate(
                        item,
                        lifecycle,
                        team_name=team_name,
                        list_tournament_winner_sources=list_tournament_winner_sources,
                    )
                )
                for item, lifecycle in selected
            ]
            return await _gather_ordered(candidate_tasks)
        finally:
            await _cancel_and_wait((*candidate_tasks, *team_tasks.values()))

    async def _build_candidate(
        self,
        item: SeriesLifecycleItem,
        lifecycle: Literal["running", "past"],
        *,
        team_name: Callable[[int], Awaitable[str | None]],
        list_tournament_winner_sources: TournamentWinnerSourceReader,
    ) -> RecentSeriesCandidate:
        champion_name = None
        champion_source: Literal["series", "tournament"] | None = None
        champion_tournament_id = None
        if lifecycle == "past":
            if item.winner_id is not None:
                if item.winner_type == "Team":
                    champion_name = await team_name(item.winner_id)
                    if champion_name is not None:
                        champion_source = "series"
            else:
                try:
                    tournament_sources = await list_tournament_winner_sources(
                        series_id=item.id
                    )
                except _ProviderError:
                    tournament_sources = []
                playoffs = next(
                    (
                        source
                        for source in tournament_sources
                        if (source.name or "").strip().casefold() == "playoffs"
                    ),
                    None,
                )
                if (
                    playoffs is not None
                    and playoffs.winner_type == "Team"
                    and playoffs.winner_id is not None
                ):
                    champion_name = await team_name(playoffs.winner_id)
                    if champion_name is not None:
                        champion_source = "tournament"
                        champion_tournament_id = playoffs.id
        return RecentSeriesCandidate(
            series_id=item.id,
            name=item.full_name or item.name,
            league_name=item.league_name,
            lifecycle=lifecycle,
            begin_at=item.begin_at,
            end_at=item.end_at,
            champion_name=champion_name,
            champion_source=champion_source,
            champion_tournament_id=champion_tournament_id,
        )

    async def _resolve_team_name(
        self,
        team_id: int,
        semaphore: asyncio.Semaphore,
    ) -> str | None:
        try:
            async with semaphore:
                result = await self._search_team(TeamSearchInput(id=team_id, limit=1))
        except _OPTIONAL_TEAM_ERRORS:
            return None
        team = next((item for item in result.items if item.id == team_id), None)
        if team is None:
            return None
        name = team.name.strip()
        return name or None


async def _gather_ordered(tasks: list[asyncio.Task[_T]]) -> list[_T]:
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        await _cancel_and_wait(tasks)
        raise


async def _cancel_and_wait(tasks: Iterable[asyncio.Task[Any]]) -> None:
    owned_tasks = tuple(tasks)
    for task in owned_tasks:
        if not task.done():
            task.cancel()
    if owned_tasks:
        await asyncio.gather(*owned_tasks, return_exceptions=True)


def _require_mappable_response(result: SeriesLifecycleResult) -> None:
    if not result.items and result.anomalies:
        raise PandaScoreProtocolError("lifecycle response contained no mappable rows")


def _select_candidates(
    running: list[SeriesLifecycleItem],
    past: list[SeriesLifecycleItem],
) -> list[tuple[SeriesLifecycleItem, Literal["running", "past"]]]:
    ordered = [
        *((item, "running") for item in _sort_by_date(running, field="begin_at")),
        *((item, "past") for item in _sort_by_date(past, field="end_at")),
    ]
    selected: list[tuple[SeriesLifecycleItem, Literal["running", "past"]]] = []
    seen_ids: set[int] = set()
    for item, lifecycle in ordered:
        if item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        selected.append((item, lifecycle))
        if len(selected) == _CANDIDATE_LIMIT:
            break
    return selected


def _sort_by_date(
    items: list[SeriesLifecycleItem],
    *,
    field: Literal["begin_at", "end_at"],
) -> list[SeriesLifecycleItem]:
    def key(item: SeriesLifecycleItem) -> tuple[bool, float]:
        value = getattr(item, field)
        if value is None:
            return True, 0.0
        return False, -_as_utc(value).timestamp()

    return sorted(items, key=key)


def _is_fresh(snapshot: RecentSeriesSnapshot | None, now: datetime) -> bool:
    if snapshot is None:
        return False
    age = (now - snapshot.retrieved_at).total_seconds()
    return age < _REFRESH_SECONDS


def _failure_cooldown_active(
    entry: RecentSeriesCacheEntry,
    now: datetime,
    *,
    local_failure: tuple[datetime, str] | None,
) -> bool:
    failure_times = []
    if entry.last_error is not None and entry.last_attempt_at is not None:
        failure_times.append(entry.last_attempt_at)
    if local_failure is not None and (
        entry.last_attempt_at is None or local_failure[0] >= entry.last_attempt_at
    ):
        failure_times.append(local_failure[0])
    return any((now - failed_at).total_seconds() < _REFRESH_SECONDS for failed_at in failure_times)


def _entry_status(
    entry: RecentSeriesCacheEntry,
    now: datetime,
) -> Literal["fresh", "stale", "unavailable"]:
    if _is_fresh(entry.snapshot, now):
        return "fresh"
    return "stale" if entry.snapshot is not None else "unavailable"


def _manual_refresh_available_at(
    entry: RecentSeriesCacheEntry,
    now: datetime,
    *,
    local_failure: tuple[datetime, str] | None,
) -> datetime | None:
    available_times: list[datetime] = []
    if entry.manual_refresh_available_at is not None:
        available_times.append(entry.manual_refresh_available_at)
    if entry.last_error is not None and entry.last_attempt_at is not None:
        available_times.append(entry.last_attempt_at + timedelta(seconds=_REFRESH_SECONDS))
    if local_failure is not None and (
        entry.last_attempt_at is None or local_failure[0] >= entry.last_attempt_at
    ):
        available_times.append(local_failure[0] + timedelta(seconds=_REFRESH_SECONDS))
    active_limits = [value for value in available_times if value > now]
    return max(active_limits) if active_limits else None


def _response(
    entry: RecentSeriesCacheEntry,
    *,
    status: Literal["fresh", "stale", "unavailable"],
    server_time: datetime,
    manual_refresh_available_at: datetime | None,
    last_attempt_at: datetime | None = None,
    last_error: str | None = None,
) -> RecentSeriesResponse:
    snapshot = entry.snapshot
    return RecentSeriesResponse(
        status=status,
        items=snapshot.items if snapshot is not None else [],
        retrieved_at=snapshot.retrieved_at if snapshot is not None else None,
        last_attempt_at=last_attempt_at or entry.last_attempt_at,
        last_error=last_error if last_error is not None else entry.last_error,
        server_time=server_time,
        manual_refresh_available_at=manual_refresh_available_at,
    )


def _decode_entry(raw_hash: object) -> RecentSeriesCacheEntry:
    if not isinstance(raw_hash, Mapping):
        raise RecentSeriesCacheDataError("recent Series cache data is invalid")
    if not raw_hash:
        return RecentSeriesCacheEntry()

    fields: dict[str, str] = {}
    try:
        for raw_key, raw_value in raw_hash.items():
            key = _decode_text(raw_key)
            value = _decode_text(raw_value)
            if key in fields or key not in _CACHE_FIELDS:
                raise RecentSeriesCacheDataError("recent Series cache data is invalid")
            fields[key] = value
        if not {"last_attempt_at", "last_error"}.issubset(fields):
            # A manual request persists its cooldown before it starts provider
            # work. On an empty cache this is a valid cooldown-only hash.
            if set(fields) != {"manual_refresh_available_at"}:
                raise RecentSeriesCacheDataError("recent Series cache data is invalid")
            return RecentSeriesCacheEntry(
                manual_refresh_available_at=datetime.fromisoformat(
                    fields["manual_refresh_available_at"]
                )
            )
        snapshot = (
            RecentSeriesSnapshot.model_validate_json(fields["snapshot"])
            if "snapshot" in fields
            else None
        )
        last_attempt_at = datetime.fromisoformat(fields["last_attempt_at"])
        last_error = fields["last_error"] or None
        manual_refresh_available_at = (
            datetime.fromisoformat(fields["manual_refresh_available_at"])
            if "manual_refresh_available_at" in fields
            else None
        )
        if last_error is not None and last_error not in _ERROR_CODES:
            raise RecentSeriesCacheDataError("recent Series cache data is invalid")
        return RecentSeriesCacheEntry(
            snapshot=snapshot,
            last_attempt_at=last_attempt_at,
            last_error=last_error,
            manual_refresh_available_at=manual_refresh_available_at,
        )
    except RecentSeriesCacheDataError:
        raise
    except (UnicodeDecodeError, ValidationError, TypeError, ValueError):
        raise RecentSeriesCacheDataError("recent Series cache data is invalid") from None


def _decode_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8")
    raise TypeError("cache field is not text")


def _validate_aware_datetime(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cache timestamps must include a timezone")


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _provider_error_code(exc: Exception) -> str:
    if isinstance(exc, PandaScoreConfigurationError):
        return "configuration_error"
    if isinstance(exc, PandaScoreProtocolError):
        return "invalid_response"
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
        return "invalid_response"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return "http_error"
    return "transport_error"


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "HomepageRecentSeriesService",
    "RecentSeriesCacheDataError",
    "RecentSeriesCacheEntry",
    "RecentSeriesCacheUnavailableError",
    "RecentSeriesCandidate",
    "RecentSeriesResponse",
    "RecentSeriesSnapshot",
    "RedisRecentSeriesCache",
]
