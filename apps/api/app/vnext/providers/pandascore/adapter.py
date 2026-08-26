"""HTTP-only PandaScore adapter for the Phase 2 Dota capabilities."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from app.vnext.providers.common import ProviderBatch, ProviderObject
from app.vnext.providers.pandascore.models import (
    PandaScoreLeague,
    PandaScoreMatch,
    PandaScoreSeries,
)

PandaMatchScope = Literal["upcoming", "recent", "running", "all"]


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
    ) -> ProviderBatch[PandaScoreSeries]:
        params: dict[str, Any] = self._page_params(limit)
        if query:
            params["search[name]"] = query
        if year is not None:
            params["filter[year]"] = year
        payload, fetched_at = await self._get_json("/dota2/series", params=params)
        rows = self._require_list(payload, "/dota2/series")
        return ProviderBatch(
            items=[self._parse(PandaScoreSeries, row, "/dota2/series") for row in rows],
            fetched_at=fetched_at,
        )

    async def search_leagues(
        self,
        *,
        query: str | None = None,
        limit: int = 20,
    ) -> ProviderBatch[PandaScoreLeague]:
        params: dict[str, Any] = self._page_params(limit)
        if query:
            params["search[name]"] = query
        payload, fetched_at = await self._get_json("/dota2/leagues", params=params)
        rows = self._require_list(payload, "/dota2/leagues")
        return ProviderBatch(
            items=[self._parse(PandaScoreLeague, row, "/dota2/leagues") for row in rows],
            fetched_at=fetched_at,
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
        payload, fetched_at = await self._get_json(path, params=params)
        rows = self._require_list(payload, path)
        return ProviderBatch(
            items=[self._parse(PandaScoreSeries, row, path) for row in rows],
            fetched_at=fetched_at,
        )

    async def list_matches(
        self,
        *,
        scope: PandaMatchScope = "all",
        series_id: int | None = None,
        query: str | None = None,
        limit: int = 20,
    ) -> ProviderBatch[PandaScoreMatch]:
        scopes = ("upcoming", "running", "recent") if scope == "all" else (scope,)
        all_items: dict[int, PandaScoreMatch] = {}
        fetched_at = datetime.now(timezone.utc)
        for item_scope in scopes:
            path_scope = "past" if item_scope == "recent" else item_scope
            params: dict[str, Any] = self._page_params(limit)
            if series_id is not None:
                params["filter[serie_id]"] = series_id
            if query:
                params["search[name]"] = query
            params["sort"] = "-scheduled_at" if item_scope == "recent" else "scheduled_at"
            payload, fetched_at = await self._get_json(
                f"/dota2/matches/{path_scope}",
                params=params,
            )
            rows = self._require_list(payload, f"/dota2/matches/{path_scope}")
            for row in rows:
                match = self._parse(PandaScoreMatch, row, f"/dota2/matches/{path_scope}")
                all_items[match.provider_id] = match
        items = list(all_items.values())
        return ProviderBatch(items=items[: max(1, limit)], fetched_at=fetched_at)

    async def list_series_matches(
        self,
        series_id: int,
        *,
        scope: Literal["upcoming", "running", "past"] = "past",
        limit: int = 20,
    ) -> ProviderBatch[PandaScoreMatch]:
        """Use PandaScore's series-scoped endpoint when a caller needs it."""

        params = self._page_params(limit)
        payload, fetched_at = await self._get_json(
            f"/series/{series_id}/matches/{scope}",
            params=params,
        )
        rows = self._require_list(payload, f"/series/{series_id}/matches/{scope}")
        return ProviderBatch(
            items=[
                self._parse(PandaScoreMatch, row, f"/series/{series_id}/matches/{scope}")
                for row in rows
            ],
            fetched_at=fetched_at,
        )

    async def get_match(self, provider_match_id: int) -> ProviderObject[PandaScoreMatch]:
        path = f"/dota2/matches/{provider_match_id}"
        payload, fetched_at = await self._get_json(path)
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
    ) -> tuple[Any, datetime]:
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
        return payload, datetime.now(timezone.utc)

    def _client_for_request(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.request_timeout_seconds,
                transport=self._transport,
            )
        return self._client

    def _page_params(self, limit: int) -> dict[str, Any]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        return {"page[size]": min(limit, self.max_page_size), "page[number]": 1}

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


__all__ = [
    "PandaMatchScope",
    "PandaScoreAdapter",
    "PandaScoreConfigurationError",
    "PandaScoreHTTPError",
    "PandaScoreProviderError",
    "PandaScoreSchemaError",
    "PandaScoreTimeoutError",
]
