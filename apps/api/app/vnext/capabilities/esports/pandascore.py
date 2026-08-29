"""PandaScore implementation of the broad esports-search capability."""

from __future__ import annotations

from hashlib import sha256
from typing import Literal

from app.vnext.domain.source import SourceLocator
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter
from app.vnext.providers.pandascore.models import (
    PandaScoreLeague,
    PandaScoreMatch,
    PandaScoreSeries,
)

from .models import EsportsSearchResult, SourceRecord

TimeScope = Literal["upcoming", "recent", "running", "all"]
_SOURCE = "pandascore"


class PandaScoreEsportsSearch:
    """Project validated PandaScore objects into bounded source-backed records."""

    def __init__(self, provider: PandaScoreAdapter) -> None:
        self._provider = provider
        self._ids_by_locator: dict[str, tuple[str, int]] = {}

    async def search(
        self,
        *,
        query: str | None,
        within: SourceLocator | None,
        time_scope: TimeScope,
        limit: int,
    ) -> EsportsSearchResult:
        if within is not None:
            return await self._search_within(
                query=query,
                within=within,
                time_scope=time_scope,
                limit=limit,
            )

        series_batch = await self._provider.search_series(query=query, limit=limit)
        league_batch = await self._provider.search_leagues(query=query, limit=limit)
        match_batch = await self._provider.list_matches(
            scope=time_scope,
            query=query,
            limit=limit,
        )
        records: list[SourceRecord] = []
        seen: set[tuple[str, int]] = set()
        for item in series_batch.items:
            self._append(records, seen, self._series_record(item), limit)
        for item in league_batch.items:
            self._append(records, seen, self._league_record(item), limit)
        for league in league_batch.items:
            if len(records) >= limit:
                break
            related = await self._provider.list_league_series(league.provider_id, limit=limit)
            for item in related.items:
                self._append(records, seen, self._series_record(item), limit)
            if related.has_more:
                break
        for item in match_batch.items:
            self._append(records, seen, self._match_record(item), limit)
        truncated = len(records) >= limit and (
            series_batch.has_more is not False
            or league_batch.has_more is not False
            or match_batch.has_more is not False
        )
        return EsportsSearchResult(records=records, truncated=truncated)

    async def _search_within(
        self,
        *,
        query: str | None,
        within: SourceLocator,
        time_scope: TimeScope,
        limit: int,
    ) -> EsportsSearchResult:
        if within.source != _SOURCE or within.kind != "series":
            return EsportsSearchResult()
        remembered = self._ids_by_locator.get(within.value)
        if remembered is None or remembered[0] != "series":
            return EsportsSearchResult()
        matches = await self._provider.list_matches(
            scope=time_scope,
            series_id=remembered[1],
            query=query,
            limit=limit,
        )
        return EsportsSearchResult(
            records=[self._match_record(item) for item in matches.items],
            truncated=matches.has_more is True,
        )

    def _append(
        self,
        records: list[SourceRecord],
        seen: set[tuple[str, int]],
        record: SourceRecord,
        limit: int,
    ) -> None:
        locator = record.locator
        if locator is None:
            return
        provider_id = self._ids_by_locator[locator.value][1]
        key = (record.kind, provider_id)
        if key not in seen and len(records) < limit:
            seen.add(key)
            records.append(record)

    def _league_record(self, item: PandaScoreLeague) -> SourceRecord:
        return SourceRecord(
            source=_SOURCE,
            kind="league",
            locator=self._locator("league", item.provider_id),
            facts={"name": item.name},
        )

    def _series_record(self, item: PandaScoreSeries) -> SourceRecord:
        return SourceRecord(
            source=_SOURCE,
            kind="series",
            locator=self._locator("series", item.provider_id),
            facts={
                "name": item.name,
                "full_name": item.full_name,
                "year": item.year,
                "season": item.season,
                "league": item.league.name if item.league else None,
                "begin_at": item.begin_at,
                "end_at": item.end_at,
                "status": item.status,
                "tier": item.tier,
                "region": item.region,
            },
        )

    def _match_record(self, item: PandaScoreMatch) -> SourceRecord:
        return SourceRecord(
            source=_SOURCE,
            kind="match",
            locator=self._locator("match", item.provider_id),
            facts={
                "name": item.name,
                "status": item.status,
                "scheduled_at": item.scheduled_at,
                "begin_at": item.begin_at,
                "end_at": item.end_at,
                "opponents": [
                    {"name": opponent.opponent.name, "acronym": opponent.opponent.acronym}
                    for opponent in item.opponents
                ],
                "number_of_games": item.number_of_games,
                "match_type": item.match_type,
                "league": item.league.name if item.league else None,
                "series": (
                    item.series.full_name or item.series.name
                    if item.series is not None
                    else None
                ),
                "tournament": item.tournament.name if item.tournament else None,
            },
        )

    def _locator(self, kind: str, provider_id: int) -> SourceLocator:
        value = _locator_value(kind, provider_id)
        self._ids_by_locator[value] = (kind, provider_id)
        return SourceLocator(source=_SOURCE, kind=kind, value=value)


def _locator_value(kind: str, provider_id: int) -> str:
    payload = f"{_SOURCE}\x1f{kind}\x1f{provider_id}".encode()
    return f"src:{sha256(payload).hexdigest()[:24]}"


__all__ = ["PandaScoreEsportsSearch", "TimeScope"]
