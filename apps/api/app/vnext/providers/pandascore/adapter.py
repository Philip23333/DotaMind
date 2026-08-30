"""HTTP-only PandaScore adapter for the Phase 2 Dota capabilities."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from app.vnext.providers.common import ProviderBatch, ProviderObject
from app.vnext.providers.pandascore.models import (
    PandaScoreLeague,
    PandaScoreMatch,
    PandaScorePlayer,
    PandaScoreSeries,
    PandaScoreTeam,
    PandaScoreTournament,
)

PandaLifecycleScope = Literal["upcoming", "running", "past"]
PandaMatchScope = Literal["upcoming", "running", "past", "recent", "all"]


@dataclass(frozen=True, slots=True)
class _PandaScorePagination:
    page_number: int
    page_size: int
    total_count: int | None = None
    link_has_next: bool | None = None
    has_more: bool | None = None


class PandaScoreProviderError(RuntimeError):
    """Base class for sanitized PandaScore adapter failures."""


class PandaScoreConfigurationError(PandaScoreProviderError):
    """The adapter was called without the required credential."""


class PandaScoreTimeoutError(PandaScoreProviderError):
    """PandaScore did not respond before the configured timeout."""


class PandaScoreHTTPError(PandaScoreProviderError):
    """PandaScore returned an unsuccessful HTTP response."""

    def __init__(self, status_code: int, path: str) -> None:
        self.status_code = status_code
        self.path = path
        super().__init__(f"PandaScore request returned HTTP {status_code}")


class PandaScoreSchemaError(PandaScoreProviderError):
    """PandaScore returned a payload outside the adapter contract."""


class PandaScoreAdapter:
    """Bearer-authenticated, provider-schema-aware PandaScore client.

    A client is created lazily on first use. Tests may inject an AsyncClient or
    MockTransport; production composition only supplies configuration.
    """

    def __init__(
        self,
        base_url: str = "https://api.pandascore.co",
        token: str | None = None,
        *,
        request_timeout_seconds: float = 20.0,
        max_page_size: int = 100,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("provide either client or transport, not both")
        self.base_url = base_url.rstrip("/")
        self.token = token.strip() if isinstance(token, str) and token.strip() else None
        self.request_timeout_seconds = request_timeout_seconds
        self.max_page_size = min(max(1, max_page_size), 100)
        self._client = client
        self._transport = transport
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None if self._owns_client else self._client

    async def search_series(
        self,
        *,
        query: str | None = None,
        year: int | None = None,
        limit: int = 20,
        page_number: int = 1,
    ) -> ProviderBatch[PandaScoreSeries]:
        params: dict[str, Any] = self._page_params(limit, page_number=page_number)
        if query:
            params["search[name]"] = query
        if year is not None:
            params["filter[year]"] = year
        payload, fetched_at, pagination = await self._get_json("/dota2/series", params=params)
        rows = self._require_list(payload, "/dota2/series")
        pagination = _complete_pagination(pagination, len(rows))
        return ProviderBatch(
            items=[self._parse(PandaScoreSeries, row, "/dota2/series") for row in rows],
            fetched_at=fetched_at,
            has_more=pagination.has_more,
        )

    async def list_series(
        self,
        scope: PandaLifecycleScope,
        *,
        query: str | None = None,
        limit: int = 20,
        page_number: int = 1,
    ) -> ProviderBatch[PandaScoreSeries]:
        path = f"/dota2/series/{scope}"
        params: dict[str, Any] = self._page_params(limit, page_number=page_number)
        if query:
            params["search[name]"] = query
        payload, fetched_at, pagination = await self._get_json(path, params=params)
        rows = self._require_list(payload, path)
        pagination = _complete_pagination(pagination, len(rows))
        return ProviderBatch(
            items=[self._parse(PandaScoreSeries, row, path) for row in rows],
            fetched_at=fetched_at,
            has_more=pagination.has_more,
        )

    async def search_leagues(
        self,
        *,
        query: str | None = None,
        limit: int = 20,
        page_number: int = 1,
    ) -> ProviderBatch[PandaScoreLeague]:
        params: dict[str, Any] = self._page_params(limit, page_number=page_number)
        if query:
            params["search[name]"] = query
        payload, fetched_at, pagination = await self._get_json("/dota2/leagues", params=params)
        rows = self._require_list(payload, "/dota2/leagues")
        pagination = _complete_pagination(pagination, len(rows))
        return ProviderBatch(
            items=[self._parse(PandaScoreLeague, row, "/dota2/leagues") for row in rows],
            fetched_at=fetched_at,
            has_more=pagination.has_more,
        )

    async def list_league_series(
        self,
        league_id: int,
        *,
        year: int | None = None,
        limit: int = 20,
    ) -> ProviderBatch[PandaScoreSeries]:
        path = f"/leagues/{league_id}/series"
        params = self._page_params(limit)
        if year is not None:
            params["filter[year]"] = year
        payload, fetched_at, pagination = await self._get_json(path, params=params)
        rows = self._require_list(payload, path)
        pagination = _complete_pagination(pagination, len(rows))
        return ProviderBatch(
            items=[self._parse(PandaScoreSeries, row, path) for row in rows],
            fetched_at=fetched_at,
            has_more=pagination.has_more,
        )

    async def search_teams(
        self,
        *,
        query: str | None = None,
        limit: int = 20,
        page_number: int = 1,
    ) -> ProviderBatch[PandaScoreTeam]:
        params = self._page_params(limit, page_number=page_number)
        if query:
            params["search[name]"] = query
        path = "/dota2/teams"
        payload, fetched_at, pagination = await self._get_json(path, params=params)
        rows = self._require_list(payload, path)
        pagination = _complete_pagination(pagination, len(rows))
        return ProviderBatch(
            items=[self._parse(PandaScoreTeam, row, path) for row in rows],
            fetched_at=fetched_at,
            has_more=pagination.has_more,
        )

    async def get_team(self, provider_team_id: int) -> ProviderObject[PandaScoreTeam]:
        path = f"/teams/{provider_team_id}"
        payload, fetched_at, _ = await self._get_json(path)
        if not isinstance(payload, dict):
            raise PandaScoreSchemaError(f"PandaScore response at {path} must be an object")
        return ProviderObject(
            item=self._parse(PandaScoreTeam, payload, path),
            fetched_at=fetched_at,
        )

    async def search_players(
        self,
        *,
        query: str | None = None,
        limit: int = 20,
        page_number: int = 1,
    ) -> ProviderBatch[PandaScorePlayer]:
        params = self._page_params(limit, page_number=page_number)
        if query:
            params["search[name]"] = query
        path = "/dota2/players"
        payload, fetched_at, pagination = await self._get_json(path, params=params)
        rows = self._require_list(payload, path)
        pagination = _complete_pagination(pagination, len(rows))
        return ProviderBatch(
            items=[self._parse(PandaScorePlayer, row, path) for row in rows],
            fetched_at=fetched_at,
            has_more=pagination.has_more,
        )

    async def search_tournaments(
        self,
        *,
        query: str | None = None,
        limit: int = 20,
        page_number: int = 1,
    ) -> ProviderBatch[PandaScoreTournament]:
        path = "/dota2/tournaments"
        params = self._page_params(limit, page_number=page_number)
        if query:
            params["search[name]"] = query
        payload, fetched_at, pagination = await self._get_json(path, params=params)
        rows = self._require_list(payload, path)
        pagination = _complete_pagination(pagination, len(rows))
        return ProviderBatch(
            items=[self._parse(PandaScoreTournament, row, path) for row in rows],
            fetched_at=fetched_at,
            has_more=pagination.has_more,
        )

    async def list_tournaments(
        self,
        scope: PandaLifecycleScope,
        *,
        query: str | None = None,
        limit: int = 20,
        page_number: int = 1,
    ) -> ProviderBatch[PandaScoreTournament]:
        path = f"/dota2/tournaments/{scope}"
        params = self._page_params(limit, page_number=page_number)
        if query:
            params["search[name]"] = query
        payload, fetched_at, pagination = await self._get_json(path, params=params)
        rows = self._require_list(payload, path)
        pagination = _complete_pagination(pagination, len(rows))
        return ProviderBatch(
            items=[self._parse(PandaScoreTournament, row, path) for row in rows],
            fetched_at=fetched_at,
            has_more=pagination.has_more,
        )

    async def get_player(self, provider_player_id: int) -> ProviderObject[PandaScorePlayer]:
        path = f"/players/{provider_player_id}"
        payload, fetched_at, _ = await self._get_json(path)
        if not isinstance(payload, dict):
            raise PandaScoreSchemaError(f"PandaScore response at {path} must be an object")
        return ProviderObject(
            item=self._parse(PandaScorePlayer, payload, path),
            fetched_at=fetched_at,
        )

    async def list_matches(
        self,
        *,
        scope: PandaMatchScope = "all",
        series_id: int | None = None,
        query: str | None = None,
        limit: int = 20,
        page_number: int = 1,
        sort: str | None = None,
    ) -> ProviderBatch[PandaScoreMatch]:
        scopes = ("upcoming", "running", "past") if scope == "all" else (scope,)
        all_items: dict[int, PandaScoreMatch] = {}
        fetched_at = datetime.now(timezone.utc)
        pages: list[_PandaScorePagination] = []
        for item_scope in scopes:
            path_scope = "past" if item_scope == "recent" else item_scope
            params: dict[str, Any] = self._page_params(limit, page_number=page_number)
            if series_id is not None:
                params["filter[serie_id]"] = series_id
            if query:
                params["search[name]"] = query
            params["sort"] = sort or (
                "-scheduled_at" if item_scope in {"recent", "past"} else "scheduled_at"
            )
            payload, page_fetched_at, pagination = await self._get_json(
                f"/dota2/matches/{path_scope}",
                params=params,
            )
            fetched_at = max(fetched_at, page_fetched_at)
            rows = self._require_list(payload, f"/dota2/matches/{path_scope}")
            pages.append(_complete_pagination(pagination, len(rows)))
            for row in rows:
                match = self._parse(PandaScoreMatch, row, f"/dota2/matches/{path_scope}")
                all_items[match.provider_id] = match
        items = list(all_items.values())
        result_limit = max(1, limit)
        has_more = _merge_pagination(pages)
        if len(items) > result_limit:
            has_more = True
        return ProviderBatch(
            items=items[:result_limit],
            fetched_at=fetched_at,
            has_more=has_more,
        )

    async def list_series_matches(
        self,
        series_id: int,
        *,
        scope: Literal["upcoming", "running", "past"] = "past",
        limit: int = 20,
    ) -> ProviderBatch[PandaScoreMatch]:
        """Use PandaScore's series-scoped endpoint when a caller needs it."""

        params = self._page_params(limit)
        payload, fetched_at, pagination = await self._get_json(
            f"/series/{series_id}/matches/{scope}",
            params=params,
        )
        rows = self._require_list(payload, f"/series/{series_id}/matches/{scope}")
        pagination = _complete_pagination(pagination, len(rows))
        return ProviderBatch(
            items=[
                self._parse(PandaScoreMatch, row, f"/series/{series_id}/matches/{scope}")
                for row in rows
            ],
            fetched_at=fetched_at,
            has_more=pagination.has_more,
        )

    async def list_team_matches(
        self,
        team_id: int,
        *,
        page_number: int = 1,
        page_size: int = 20,
        sort: Literal["scheduled_at", "-scheduled_at"] | None = None,
        query: str | None = None,
        series_id: int | None = None,
    ) -> ProviderBatch[PandaScoreMatch]:
        """List matches through PandaScore's team relationship endpoint."""

        path = f"/teams/{team_id}/matches"
        params = self._page_params(page_size, page_number=page_number)
        if sort is not None:
            params["sort"] = sort
        if query:
            params["search[name]"] = query
        if series_id is not None:
            params["filter[serie_id]"] = series_id
        payload, fetched_at, pagination = await self._get_json(path, params=params)
        rows = self._require_list(payload, path)
        pagination = _complete_pagination(pagination, len(rows))
        return ProviderBatch(
            items=[self._parse(PandaScoreMatch, row, path) for row in rows],
            fetched_at=fetched_at,
            has_more=pagination.has_more,
        )

    async def get_match(self, provider_match_id: int) -> ProviderObject[PandaScoreMatch]:
        path = f"/matches/{provider_match_id}"
        payload, fetched_at, _ = await self._get_json(path)
        if not isinstance(payload, dict):
            raise PandaScoreSchemaError(f"PandaScore response at {path} must be an object")
        return ProviderObject(
            item=self._parse(PandaScoreMatch, payload, path),
            fetched_at=fetched_at,
        )

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> tuple[Any, datetime, _PandaScorePagination]:
        if not self.token:
            raise PandaScoreConfigurationError("PandaScore token is not configured")
        client = self._client_for_request()
        try:
            response = await client.get(
                path,
                params=params,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/json",
                },
            )
        except httpx.TimeoutException as exc:
            raise PandaScoreTimeoutError("PandaScore request timed out") from exc
        except httpx.HTTPError as exc:
            raise PandaScoreProviderError("PandaScore request failed") from exc
        if response.status_code >= 400:
            raise PandaScoreHTTPError(response.status_code, path)
        try:
            payload = response.json()
        except ValueError as exc:
            raise PandaScoreSchemaError("PandaScore response was not valid JSON") from exc
        page_number = _positive_int((params or {}).get("page[number]"), default=1)
        page_size = _positive_int(
            (params or {}).get("page[size]"),
            default=self.max_page_size,
        )
        total_count = _header_int(response.headers.get("x-total"))
        link_has_next = _link_has_next(response.headers.get("link"))
        if link_has_next is not None:
            has_more = link_has_next
        elif total_count is not None:
            has_more = page_number * page_size < total_count
        else:
            has_more = None
        return (
            payload,
            datetime.now(timezone.utc),
            _PandaScorePagination(
                page_number=page_number,
                page_size=page_size,
                total_count=total_count,
                link_has_next=link_has_next,
                has_more=has_more,
            ),
        )

    def _client_for_request(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.request_timeout_seconds,
                transport=self._transport,
            )
        return self._client

    def _page_params(self, limit: int, *, page_number: int = 1) -> dict[str, Any]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        if page_number < 1:
            raise ValueError("page_number must be greater than zero")
        return {
            "page[size]": min(limit, self.max_page_size),
            "page[number]": page_number,
        }

    @staticmethod
    def _require_list(payload: Any, path: str) -> list[Any]:
        if not isinstance(payload, list):
            raise PandaScoreSchemaError(f"PandaScore response at {path} must be a list")
        return payload

    @staticmethod
    def _parse(model: type[Any], payload: Any, path: str) -> Any:
        try:
            return model.model_validate(payload)
        except (ValidationError, TypeError, ValueError) as exc:
            raise PandaScoreSchemaError(f"PandaScore response at {path} was invalid") from exc


def _complete_pagination(
    pagination: _PandaScorePagination,
    item_count: int,
) -> _PandaScorePagination:
    if pagination.has_more is not None:
        return pagination
    return replace(pagination, has_more=item_count == pagination.page_size)


def _merge_pagination(pages: list[_PandaScorePagination]) -> bool | None:
    if any(page.has_more is True for page in pages):
        return True
    if pages and all(page.has_more is False for page in pages):
        return False
    return None


def _positive_int(value: Any, *, default: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0 else default


def _header_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        result = int(value.strip())
    except (AttributeError, TypeError, ValueError):
        return None
    return result if result >= 0 else None


_LINK_RELATION_PATTERN = re.compile(
    r'(?:^|;)\s*rel\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^,;\s]+))',
    re.IGNORECASE,
)


def _link_has_next(value: str | None) -> bool | None:
    if not value:
        return None

    saw_relation = False
    for link_value in value.split(","):
        _, separator, parameters = link_value.partition(">")
        if not separator:
            parameters = link_value
        match = _LINK_RELATION_PATTERN.search(parameters)
        if match is None:
            continue
        saw_relation = True
        relation_value = next(group for group in match.groups() if group is not None)
        if any(relation.casefold() == "next" for relation in relation_value.split()):
            return True
    return False if saw_relation else None


__all__ = [
    "PandaLifecycleScope",
    "PandaMatchScope",
    "PandaScoreAdapter",
    "PandaScoreConfigurationError",
    "PandaScoreHTTPError",
    "PandaScoreProviderError",
    "PandaScoreSchemaError",
    "PandaScoreTimeoutError",
]
