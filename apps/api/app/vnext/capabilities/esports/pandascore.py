"""PandaScore implementation of the broad esports-search capability."""

from __future__ import annotations

from typing import Literal

from app.vnext.domain.common.models import normalize_text
from app.vnext.domain.source import SourceLocator, SourceLocatorError
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter
from app.vnext.providers.pandascore.locator import PandaScoreLocatorIndex
from app.vnext.providers.pandascore.models import (
    PandaScoreGame,
    PandaScoreLeague,
    PandaScoreMatch,
    PandaScoreSeries,
    PandaScoreTeam,
)

from .models import EsportsSearchResult, SourceRecord

TimeScope = Literal["upcoming", "recent", "running", "all"]
_SOURCE = "pandascore"
_TEAM_SEARCH_LIMIT = 20
_TEAM_MATCH_PAGE_SIZE = 100
_TEAM_MATCH_MAX_PAGES = 5


class PandaScoreEsportsSearch:
    """Project validated PandaScore objects into bounded source-backed records."""

    def __init__(self, provider: PandaScoreAdapter, locators: PandaScoreLocatorIndex) -> None:
        self._provider = provider
        self._locators = locators

    async def search(
        self,
        *,
        query: str | None,
        within: SourceLocator | None,
        teams: list[str],
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
        if teams:
            return await self._search_by_teams(
                query=query,
                teams=teams,
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
        resolved = self._locators.resolve(within)
        if resolved.kind == "league":
            series = await self._provider.list_league_series(resolved.provider_id, limit=limit)
            records = [self._series_record(item) for item in series.items]
            return EsportsSearchResult(records=records, truncated=series.has_more is not False)
        if resolved.kind == "series":
            matches = await self._provider.list_matches(
                scope=time_scope,
                series_id=resolved.provider_id,
                query=query,
                limit=limit,
            )
            return EsportsSearchResult(
                records=[self._match_record(item) for item in matches.items],
                truncated=matches.has_more is not False,
            )
        if resolved.kind == "match":
            match = await self._provider.get_match(resolved.provider_id)
            games = match.item.games[:limit]
            return EsportsSearchResult(
                records=[self._game_record(item, match.item) for item in games],
                truncated=len(match.item.games) > limit,
            )
        raise SourceLocatorError(
            "source locator kind does not support esports navigation",
            details={"source": within.source, "kind": within.kind},
        )

    async def _search_by_teams(
        self,
        *,
        query: str | None,
        teams: list[str],
        time_scope: TimeScope,
        limit: int,
    ) -> EsportsSearchResult:
        normalized_teams = [item.strip() for item in teams if item.strip()]
        if len(normalized_teams) != len(teams):
            return EsportsSearchResult()
        resolved_ids: set[int] = set()
        for team_query in normalized_teams:
            batch = await self._provider.search_teams(query=team_query, limit=_TEAM_SEARCH_LIMIT)
            matches = _exact_team_matches(team_query, batch.items)
            if len(matches) != 1:
                return EsportsSearchResult()
            resolved_ids.add(matches[0].provider_id)
        if len(resolved_ids) != len(normalized_teams):
            return EsportsSearchResult()

        records: list[SourceRecord] = []
        seen: set[int] = set()
        truncated = False
        for page_number in range(1, _TEAM_MATCH_MAX_PAGES + 1):
            batch = await self._provider.list_team_matches(
                next(iter(resolved_ids)),
                page_number=page_number,
                page_size=_TEAM_MATCH_PAGE_SIZE,
                sort="scheduled_at" if time_scope == "upcoming" else "-scheduled_at",
            )
            for item in batch.items:
                if not _has_provider_teams(item, resolved_ids):
                    continue
                if not _time_scope_matches(item, time_scope) or not _match_query(item, query):
                    continue
                if item.provider_id in seen:
                    continue
                seen.add(item.provider_id)
                if len(records) >= limit:
                    truncated = True
                    continue
                records.append(self._match_record(item))
            if len(records) >= limit:
                truncated = truncated or batch.has_more is not False
                break
            if batch.has_more is False:
                break
            if page_number == _TEAM_MATCH_MAX_PAGES:
                truncated = True
        return EsportsSearchResult(records=records, truncated=truncated)

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
        provider_id = self._locators.resolve(locator).provider_id
        key = (record.kind, provider_id)
        if key not in seen and len(records) < limit:
            seen.add(key)
            records.append(record)

    def _league_record(self, item: PandaScoreLeague) -> SourceRecord:
        return SourceRecord(
            source=_SOURCE,
            kind="league",
            locator=self._locators.make("league", item.provider_id),
            facts={"name": item.name},
        )

    def _series_record(self, item: PandaScoreSeries) -> SourceRecord:
        return SourceRecord(
            source=_SOURCE,
            kind="series",
            locator=self._locators.make("series", item.provider_id),
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
            locator=self._locators.make("match", item.provider_id),
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

    def _game_record(self, item: PandaScoreGame, match: PandaScoreMatch) -> SourceRecord:
        locator = self._locators.make("game", item.provider_id)
        self._locators.remember_game_parent(item.provider_id, match.provider_id)
        return SourceRecord(
            source=_SOURCE,
            kind="game",
            locator=locator,
            facts={
                "position": item.position,
                "status": item.status,
                "scheduled_at": item.scheduled_at,
                "begin_at": item.begin_at,
                "end_at": item.end_at,
                "length": item.length,
                "winner": item.winner.name if item.winner else None,
                "complete": item.complete,
                "detailed_stats": item.detailed_stats,
            },
        )


def _exact_team_matches(query: str, candidates: list[PandaScoreTeam]) -> list[PandaScoreTeam]:
    needle = normalize_text(query)
    matches: dict[int, PandaScoreTeam] = {}
    for candidate in candidates:
        values = (candidate.name, candidate.acronym, candidate.slug)
        if any(value and normalize_text(value) == needle for value in values):
            matches[candidate.provider_id] = candidate
    return list(matches.values())


def _has_provider_teams(row: PandaScoreMatch, team_ids: set[int]) -> bool:
    return team_ids.issubset({item.opponent.provider_id for item in row.opponents})


def _time_scope_matches(row: PandaScoreMatch, time_scope: TimeScope) -> bool:
    if time_scope == "recent":
        return row.status == "finished"
    if time_scope == "upcoming":
        return row.status == "not_started"
    if time_scope == "running":
        return row.status == "running"
    return True


def _match_query(row: PandaScoreMatch, query: str | None) -> bool:
    if not query:
        return True
    tokens = [
        token
        for token in normalize_text(query).split()
        if token not in {"and", "vs", "v", "versus", "against"}
    ]
    values = [row.name, *(item.opponent.name for item in row.opponents)]
    if row.series is not None:
        values.extend([row.series.name or "", row.series.full_name or ""])
    return all(token in normalize_text(" ".join(values)) for token in tokens)


__all__ = ["PandaScoreEsportsSearch", "TimeScope"]
