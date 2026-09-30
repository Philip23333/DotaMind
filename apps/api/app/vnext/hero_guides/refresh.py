"""Sequential, internal executor for refreshing cached D2PT hero guides."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.vnext.providers.d2pt import D2PTClient, D2PTError, D2PTResponse
from app.vnext.providers.d2pt.parsers import parse_pro_examples, parse_pub_builds

from .cache import GuideCacheSnapshot, HeroGuideWriter

SampleType = Literal["pub", "pro"]
RefreshStatus = Literal["success", "partial", "failed"]
_REQUEST_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class HeroGuideRefreshFailure:
    sample_type: SampleType
    hero_id: int
    position: int | None
    error_code: str


@dataclass(frozen=True, slots=True)
class HeroGuideRefreshReport:
    status: RefreshStatus
    started_at: datetime
    finished_at: datetime
    hero_count: int
    request_count: int
    pub_published: int
    pro_published: int
    pub_empty: int
    pro_empty: int
    failures: list[HeroGuideRefreshFailure]
    heroes_error: str | None = None


class HeroGuideRefresher:
    """Refresh every hero partition serially using injected client and cache."""

    def __init__(
        self,
        client: D2PTClient,
        cache: HeroGuideWriter,
        *,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._client = client
        self._cache = cache
        self._clock = (lambda: datetime.now(UTC)) if clock is None else clock
        self._sleep = asyncio.sleep if sleep is None else sleep
        self._request_count = 0

    async def refresh_all(self) -> HeroGuideRefreshReport:
        """Refresh all Pub positions and Pro examples in source hero order."""

        self._request_count = 0
        started_at = self._now()
        try:
            heroes_response = await self._request(self._client.heroes_list)
        except D2PTError as exc:
            return HeroGuideRefreshReport(
                status="failed",
                started_at=started_at,
                finished_at=self._now(),
                hero_count=0,
                request_count=self._request_count,
                pub_published=0,
                pro_published=0,
                pub_empty=0,
                pro_empty=0,
                failures=[],
                heroes_error=exc.code,
            )

        heroes = [row["hero_id"] for row in heroes_response.data]
        failures: list[HeroGuideRefreshFailure] = []
        pub_published = 0
        pro_published = 0
        pub_empty = 0
        pro_empty = 0

        for hero_id in heroes:
            for position in range(1, 6):
                attempted_at = self._now()
                try:
                    response = await self._request(
                        self._client.pub_builds,
                        hero_id,
                        position,
                    )
                    guides = parse_pub_builds(
                        response.data,
                        hero_id=hero_id,
                        position=position,
                    )
                except D2PTError as exc:
                    await self._record_failure(
                        failures,
                        sample_type="pub",
                        hero_id=hero_id,
                        position=position,
                        attempted_at=attempted_at,
                        error=exc,
                    )
                    continue

                snapshot = GuideCacheSnapshot(
                    sample_type="pub",
                    hero_id=hero_id,
                    position=position,
                    retrieved_at=response.retrieved_at,
                    content_type=response.content_type,
                    raw_body=response.raw_body,
                    source_rows=response.data,
                    pub_guides=guides,
                )
                await self._cache.publish(snapshot, attempted_at=attempted_at)
                pub_published += 1
                if not response.data:
                    pub_empty += 1

            attempted_at = self._now()
            try:
                response = await self._request(self._client.pro_builds, hero_id)
                examples = parse_pro_examples(response.data, hero_id=hero_id)
            except D2PTError as exc:
                await self._record_failure(
                    failures,
                    sample_type="pro",
                    hero_id=hero_id,
                    position=None,
                    attempted_at=attempted_at,
                    error=exc,
                )
                continue

            snapshot = GuideCacheSnapshot(
                sample_type="pro",
                hero_id=hero_id,
                position=None,
                retrieved_at=response.retrieved_at,
                content_type=response.content_type,
                raw_body=response.raw_body,
                source_rows=response.data,
                pro_examples=examples,
            )
            await self._cache.publish(snapshot, attempted_at=attempted_at)
            pro_published += 1
            if not response.data:
                pro_empty += 1

        finished_at = self._now()
        status: RefreshStatus
        if not failures:
            status = "success"
        elif pub_published + pro_published:
            status = "partial"
        else:
            status = "failed"

        return HeroGuideRefreshReport(
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            hero_count=len(heroes),
            request_count=self._request_count,
            pub_published=pub_published,
            pro_published=pro_published,
            pub_empty=pub_empty,
            pro_empty=pro_empty,
            failures=failures,
        )

    async def _request(
        self,
        method: Callable[..., D2PTResponse],
        *args: object,
    ) -> D2PTResponse:
        self._request_count += 1
        request_error: D2PTError | None = None
        response: D2PTResponse | None = None
        try:
            response = await asyncio.to_thread(method, *args)
        except D2PTError as exc:
            request_error = exc

        await self._sleep(_REQUEST_INTERVAL_SECONDS)
        if request_error is not None:
            raise request_error
        assert response is not None
        return response

    async def _record_failure(
        self,
        failures: list[HeroGuideRefreshFailure],
        *,
        sample_type: SampleType,
        hero_id: int,
        position: int | None,
        attempted_at: datetime,
        error: D2PTError,
    ) -> None:
        await self._cache.record_failure(
            sample_type=sample_type,
            hero_id=hero_id,
            position=position,
            attempted_at=attempted_at,
            error_code=error.code,
        )
        failures.append(
            HeroGuideRefreshFailure(
                sample_type=sample_type,
                hero_id=hero_id,
                position=position,
                error_code=error.code,
            )
        )

    def _now(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ValueError("refresh clock must return timezone-aware datetimes")
        return value


__all__ = [
    "HeroGuideRefreshFailure",
    "HeroGuideRefreshReport",
    "HeroGuideRefresher",
]
