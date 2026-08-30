"""PandaScore provider implementation for broad esports discovery."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel

from app.vnext.domain.common.models import normalize_text
from app.vnext.domain.matches.normalization import normalize_panda_match
from app.vnext.domain.matches.valve_match_id_resolver import ValveMatchIdResolver
from app.vnext.providers.common import ProviderBatch
from app.vnext.providers.opendota.adapter import OpenDotaProviderError
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter, PandaScoreProviderError
from app.vnext.providers.pandascore.models import PandaScoreMatch, PandaScoreTeam

from .errors import EsportsInvalidArgumentsError, EsportsProviderError
from .models import (
    EsportsKind,
    EsportsSearchRequest,
    ProviderEntity,
    ProviderSearchBatch,
    TimeScope,
)

_SOURCE = "pandascore"
_PAGE_SIZE = 100
_MAX_SCAN_PAGES = 5
_TEAM_SEARCH_LIMIT = 100
_T = TypeVar("_T", bound=BaseModel)
_PageFetcher = Callable[[int, int], Awaitable[ProviderBatch[_T]]]


class PandaScoreEsportsProvider:
    """Select, filter, order, and enrich PandaScore entities below the capability boundary."""

    def __init__(self, adapter: PandaScoreAdapter, resolver: ValveMatchIdResolver) -> None:
        self._adapter = adapter
        self._resolver = resolver

    async def search(self, request: EsportsSearchRequest) -> ProviderSearchBatch:
        try:
            if request.kind == "league":
                return await self._search_leagues(request)
            if request.kind == "series":
                return await self._search_series(request)
            if request.kind == "tournament":
                return await self._search_tournaments(request)
            if request.kind == "match":
                return await self._search_matches(request)
            if request.kind == "team":
                return await self._search_teams(request)
            return await self._search_players(request)
        except EsportsProviderError:
            raise
        except (OpenDotaProviderError, PandaScoreProviderError) as exc:
            raise EsportsProviderError(source=_SOURCE, kind=request.kind) from exc

    async def _search_leagues(self, request: EsportsSearchRequest) -> ProviderSearchBatch:
        items, truncated = await self._collect(
            lambda page, size: self._adapter.search_leagues(
                query=None,
                limit=size,
                page_number=page,
            ),
            lambda item: _matches_query(item, request.query),
        )
        return _entity_batch("league", items, request.limit, truncated)

    async def _search_series(self, request: EsportsSearchRequest) -> ProviderSearchBatch:
        if request.time_scope is None:

            async def fetch(page: int, size: int) -> ProviderBatch[BaseModel]:
                return await self._adapter.search_series(
                    query=None,
                    limit=size,
                    page_number=page,
                )

            def predicate(item: BaseModel) -> bool:
                return _matches_query(item, request.query)

            order = None
            reverse = False
        else:

            async def fetch(page: int, size: int) -> ProviderBatch[BaseModel]:
                return await self._adapter.list_series(
                    request.time_scope,
                    query=None,
                    limit=size,
                    page_number=page,
                )

            def predicate(item: BaseModel) -> bool:
                return _matches_query(item, request.query)

            order, reverse = _lifecycle_sort(request.time_scope)
        items, truncated = await self._collect(fetch, predicate, order_key=order, reverse=reverse)
        return _entity_batch("series", items, request.limit, truncated)

    async def _search_tournaments(self, request: EsportsSearchRequest) -> ProviderSearchBatch:
        if request.time_scope is None:

            async def fetch(page: int, size: int) -> ProviderBatch[BaseModel]:
                return await self._adapter.search_tournaments(
                    query=None,
                    limit=size,
                    page_number=page,
                )

            def predicate(item: BaseModel) -> bool:
                return _matches_query(item, request.query)

            order = None
            reverse = False
        else:

            async def fetch(page: int, size: int) -> ProviderBatch[BaseModel]:
                return await self._adapter.list_tournaments(
                    request.time_scope,
                    query=None,
                    limit=size,
                    page_number=page,
                )

            def predicate(item: BaseModel) -> bool:
                return _matches_query(item, request.query)

            order, reverse = _lifecycle_sort(request.time_scope)
        items, truncated = await self._collect(fetch, predicate, order_key=order, reverse=reverse)
        return _entity_batch("tournament", items, request.limit, truncated)

    async def _search_teams(self, request: EsportsSearchRequest) -> ProviderSearchBatch:
        items, truncated = await self._collect(
            lambda page, size: self._adapter.search_teams(
                query=None,
                limit=size,
                page_number=page,
            ),
            lambda item: _matches_query(item, request.query),
        )
        return _entity_batch("team", items, request.limit, truncated)

    async def _search_players(self, request: EsportsSearchRequest) -> ProviderSearchBatch:
        items, truncated = await self._collect(
            lambda page, size: self._adapter.search_players(
                query=None,
                limit=size,
                page_number=page,
            ),
            lambda item: _matches_query(item, request.query),
        )
        return _entity_batch("player", items, request.limit, truncated)

    async def _search_matches(self, request: EsportsSearchRequest) -> ProviderSearchBatch:
        if request.teams:
            items, truncated = await self._team_match_items(request)
        else:
            scope = request.time_scope or "all"
            items, truncated = await self._collect(
                lambda page, size: self._adapter.list_matches(
                    scope=scope,
                    query=None,
                    limit=size,
                    page_number=page,
                ),
                lambda item: _matches_query(item, request.query),
                order_key=_lifecycle_sort(request.time_scope)[0],
                reverse=_lifecycle_sort(request.time_scope)[1],
            )
        selected, over_limit = _final_provider_items(items, request.limit)
        entities = [
            ProviderEntity(
                source=_SOURCE,
                kind="match",
                source_identity=item.provider_id,
                fetched_at=fetched_at,
                document=await self._enrich_match(item, fetched_at),
            )
            for item, fetched_at in selected
        ]
        return ProviderSearchBatch(entities=entities, truncated=truncated or over_limit)

    async def _team_match_items(
        self,
        request: EsportsSearchRequest,
    ) -> tuple[list[tuple[PandaScoreMatch, datetime]], bool]:
        team_ids: list[int] = []
        seen_queries: set[str] = set()
        for team_query in request.teams:
            normalized_query = normalize_text(team_query)
            if normalized_query in seen_queries:
                continue
            seen_queries.add(normalized_query)
            batch = await self._adapter.search_teams(
                query=team_query,
                limit=_TEAM_SEARCH_LIMIT,
            )
            matches = _exact_team_matches(team_query, batch.items)
            if not matches:
                raise EsportsInvalidArgumentsError(
                    "team did not resolve to a PandaScore identity",
                    details={
                        "argument": "teams",
                        "team": team_query,
                        "reason": "not_found",
                    },
                )
            if len(matches) > 1:
                raise EsportsInvalidArgumentsError(
                    "team resolved to multiple PandaScore identities",
                    details={
                        "argument": "teams",
                        "team": team_query,
                        "reason": "ambiguous",
                        "candidate_count": len(matches),
                    },
                )
            team_ids.append(matches[0].provider_id)
        required_team_ids = set(team_ids)
        if not required_team_ids:
            return [], False
        order_key, reverse = _lifecycle_sort(request.time_scope)
        return await self._collect(
            lambda page, size: self._adapter.list_team_matches(
                team_ids[0],
                page_number=page,
                page_size=size,
                sort="scheduled_at" if request.time_scope == "upcoming" else "-scheduled_at",
            ),
            lambda item: (
                _has_provider_teams(item, required_team_ids)
                and _matches_query(item, request.query)
                and _in_scope(item, request.time_scope)
            ),
            order_key=order_key,
            reverse=reverse,
        )

    async def _collect(
        self,
        fetch: _PageFetcher[_T],
        predicate: Callable[[_T], bool],
        *,
        order_key: Callable[[_T], str] | None = None,
        reverse: bool = False,
    ) -> tuple[list[tuple[_T, datetime]], bool]:
        collected: list[tuple[_T, datetime]] = []
        complete = False
        for page_number in range(1, _MAX_SCAN_PAGES + 1):
            batch = await fetch(page_number, _PAGE_SIZE)
            collected.extend((item, batch.fetched_at) for item in batch.items if predicate(item))
            if batch.has_more is False:
                complete = True
                break
        unique: list[tuple[_T, datetime]] = []
        identities: set[int] = set()
        for item, fetched_at in collected:
            provider_id = item.provider_id
            if provider_id in identities:
                continue
            identities.add(provider_id)
            unique.append((item, fetched_at))
        if order_key is not None:
            unique.sort(key=lambda pair: order_key(pair[0]), reverse=reverse)
        return unique, not complete

    async def _enrich_match(
        self,
        match: PandaScoreMatch,
        fetched_at: datetime,
    ) -> dict[str, object]:
        document = match.model_dump(mode="json", by_alias=True)
        if not match.games:
            return document
        normalized = normalize_panda_match(match, fetched_at=fetched_at)
        games = document.get("games")
        if not isinstance(games, list):
            raise EsportsProviderError(source=_SOURCE, kind="match")
        try:
            decisions = await self._resolver.resolve_many(normalized, normalized.games)
        except OpenDotaProviderError:
            for game in games:
                if not isinstance(game, dict):
                    raise EsportsProviderError(source=_SOURCE, kind="match") from None
                game["valve_game_id"] = None
                game["resolution"] = "unavailable"
            return document
        if len(decisions) != len(match.games):
            raise EsportsProviderError(source=_SOURCE, kind="match")
        for game, decision in zip(games, decisions, strict=True):
            if not isinstance(game, dict):
                raise EsportsProviderError(source=_SOURCE, kind="match")
            game["valve_game_id"] = (
                decision.resolved_provider_match_id if decision.status == "resolved" else None
            )
            game["resolution"] = decision.status
        return document


def _entity_batch(
    kind: EsportsKind,
    items: list[tuple[BaseModel, datetime]],
    limit: int,
    truncated: bool,
) -> ProviderSearchBatch:
    selected, over_limit = _final_provider_items(items, limit)
    return ProviderSearchBatch(
        entities=[
            ProviderEntity(
                source=_SOURCE,
                kind=kind,
                source_identity=item.provider_id,
                fetched_at=fetched_at,
                document=item.model_dump(mode="json", by_alias=True),
            )
            for item, fetched_at in selected
        ],
        truncated=truncated or over_limit,
    )


def _final_provider_items(
    items: list[tuple[_T, datetime]],
    limit: int,
) -> tuple[list[tuple[_T, datetime]], bool]:
    return items[: limit + 1], len(items) > limit


def _exact_team_matches(query: str, candidates: list[PandaScoreTeam]) -> list[PandaScoreTeam]:
    needle = normalize_text(query)
    matches: dict[int, PandaScoreTeam] = {}
    for candidate in candidates:
        if any(
            value and normalize_text(value) == needle
            for value in (candidate.name, candidate.acronym, candidate.slug)
        ):
            matches[candidate.provider_id] = candidate
    return list(matches.values())


def _has_provider_teams(match: PandaScoreMatch, team_ids: set[int]) -> bool:
    return team_ids.issubset({item.opponent.provider_id for item in match.opponents})


def _matches_query(item: BaseModel, query: str | None) -> bool:
    if not query or not query.strip():
        return True
    tokens = [
        token
        for token in normalize_text(query).split()
        if token not in {"and", "vs", "v", "versus", "against"}
    ]
    if not tokens:
        return True
    text = normalize_text(" ".join(_document_strings(item.model_dump(mode="json", by_alias=True))))
    return all(token in text for token in tokens)


def _document_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [part for child in value.values() for part in _document_strings(child)]
    if isinstance(value, list):
        return [part for child in value for part in _document_strings(child)]
    return []


def _in_scope(item: BaseModel, scope: TimeScope | None) -> bool:
    if scope is None:
        return True
    document = item.model_dump(mode="json", by_alias=True)
    status = normalize_text(str(document.get("status") or "").replace("_", " "))
    if scope == "upcoming":
        return status in {"not started", "scheduled", "upcoming"}
    if scope == "running":
        return status in {"running", "live", "in progress"}
    return status not in {"not started", "scheduled", "upcoming", "running", "live", "in progress"}


def _lifecycle_sort(scope: TimeScope | None) -> tuple[Callable[[BaseModel], str] | None, bool]:
    if scope == "past":
        return _past_time, True
    if scope == "upcoming":
        return _upcoming_time, False
    if scope == "running":
        return _running_time, True
    return None, False


def _past_time(item: BaseModel) -> str:
    document = item.model_dump(mode="json", by_alias=True)
    return str(
        document.get("end_at") or document.get("begin_at") or document.get("scheduled_at") or ""
    )


def _upcoming_time(item: BaseModel) -> str:
    document = item.model_dump(mode="json", by_alias=True)
    return str(document.get("scheduled_at") or document.get("begin_at") or "~")


def _running_time(item: BaseModel) -> str:
    document = item.model_dump(mode="json", by_alias=True)
    return str(document.get("begin_at") or document.get("scheduled_at") or "")


__all__ = ["PandaScoreEsportsProvider"]
