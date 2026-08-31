"""PandaScore provider implementation for broad esports discovery."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel

from app.vnext.domain.common.models import normalize_text
from app.vnext.domain.matches.normalization import normalize_panda_match
from app.vnext.domain.matches.resolution import ResolutionDecision
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
        documents = await self._enrich_matches(selected)
        entities = [
            ProviderEntity(
                source=_SOURCE,
                kind="match",
                source_identity=item.provider_id,
                fetched_at=fetched_at,
                document=document,
            )
            for (item, fetched_at), document in zip(selected, documents, strict=True)
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
            matches = await self._resolve_team_identity_candidates(team_query)
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

    async def _resolve_team_identity_candidates(self, team_query: str) -> list[PandaScoreTeam]:
        """Scan all Team pages before declaring an exact identity cardinality."""

        matches: dict[int, PandaScoreTeam] = {}
        page_number = 1
        while True:
            batch = await self._adapter.search_teams(
                query=None,
                limit=_PAGE_SIZE,
                page_number=page_number,
            )
            for candidate in batch.items:
                if _is_exact_team_match(team_query, candidate):
                    matches[candidate.provider_id] = candidate
            if batch.has_more is False:
                return list(matches.values())
            if batch.has_more is None:
                raise EsportsProviderError(source=_SOURCE, kind="team")
            page_number += 1

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

    async def _enrich_matches(
        self,
        selected: list[tuple[PandaScoreMatch, datetime]],
    ) -> list[dict[str, object]]:
        """Enrich selected Match documents through one batch resolver invocation."""

        documents = [match.model_dump(mode="json", by_alias=True) for match, _ in selected]
        resolution_inputs = [
            (index, normalize_panda_match(match, fetched_at=fetched_at))
            for index, (match, fetched_at) in enumerate(selected)
            if match.games
        ]
        if not resolution_inputs:
            return documents
        try:
            outcomes = await self._resolver.resolve_many_matches(
                [normalized for _, normalized in resolution_inputs]
            )
        except OpenDotaProviderError:
            for index, _ in resolution_inputs:
                _mark_games_unavailable(documents[index])
            return documents
        if len(outcomes) != len(resolution_inputs):
            raise EsportsProviderError(source=_SOURCE, kind="match")
        for (index, normalized), outcome in zip(resolution_inputs, outcomes, strict=True):
            if outcome.unavailable:
                _mark_games_unavailable(documents[index])
                continue
            decisions = outcome.decisions
            if decisions is None or len(decisions) != len(normalized.games):
                raise EsportsProviderError(source=_SOURCE, kind="match")
            _apply_game_decisions(documents[index], decisions)
        return documents


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
    return items[:limit], len(items) > limit


def _mark_games_unavailable(document: dict[str, object]) -> None:
    games = _document_games(document)
    for game in games:
        game["valve_game_id"] = None
        game["resolution"] = "unavailable"


def _apply_game_decisions(
    document: dict[str, object],
    decisions: Sequence[ResolutionDecision],
) -> None:
    games = _document_games(document)
    if len(games) != len(decisions):
        raise EsportsProviderError(source=_SOURCE, kind="match")
    for game, decision in zip(games, decisions, strict=True):
        game["valve_game_id"] = (
            decision.resolved_provider_match_id if decision.status == "resolved" else None
        )
        game["resolution"] = decision.status


def _document_games(document: dict[str, object]) -> list[dict[str, object]]:
    games = document.get("games")
    if not isinstance(games, list) or not all(isinstance(game, dict) for game in games):
        raise EsportsProviderError(source=_SOURCE, kind="match")
    return games


def _is_exact_team_match(query: str, candidate: PandaScoreTeam) -> bool:
    needle = normalize_text(query)
    return any(
        value and normalize_text(value) == needle
        for value in (candidate.name, candidate.acronym, candidate.slug)
    )


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
