"""Small, auditable HTTP boundary for the PandaScore API."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx


class PandaScoreTransportError(RuntimeError):
    """The request could not be completed or decoded."""


class PandaScoreConfigurationError(PandaScoreTransportError):
    """The integration is not configured with a token."""


class PandaScoreHTTPStatusError(PandaScoreTransportError):
    """PandaScore returned an unsuccessful HTTP response."""

    def __init__(self, status_code: int, path: str, message: str = "") -> None:
        self.status_code = status_code
        self.path = path
        super().__init__(f"PandaScore HTTP {status_code} for {path}: {message}".strip())


class PandaScorePlanAccessError(PandaScoreHTTPStatusError):
    """The current PandaScore plan does not expose the requested resource."""


class PandaScoreTransport:
    """Bearer-authenticated transport with bounded response caching."""

    def __init__(
        self,
        base_url: str,
        token: str | None,
        *,
        request_timeout_seconds: float = 20,
        default_cache_ttl_seconds: int = 60,
        max_page_size: int = 100,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token.strip() if isinstance(token, str) and token.strip() else None
        self.request_timeout_seconds = request_timeout_seconds
        self.default_cache_ttl_seconds = default_cache_ttl_seconds
        self.max_page_size = max(1, min(max_page_size, 100))
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._client: httpx.AsyncClient | None = None
        self.last_rate_limit_remaining: int | None = None

    def _require_token(self) -> str:
        if not self.token:
            raise PandaScoreConfigurationError(
                "DOTAMIND_PANDASCORE_TOKEN is required for PandaScore tools"
            )
        return self.token

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        cache_ttl_seconds: int | None = None,
    ) -> Any:
        token = self._require_token()
        clean_path = "/" + path.lstrip("/")
        normalized_params = self._normalize_params(params)
        cache_key = json.dumps([clean_path, normalized_params], ensure_ascii=True, sort_keys=True)
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if cached is not None and now < cached[0]:
            self._cache_hits += 1
            return cached[1]

        self._cache_misses += 1
        try:
            response = await self.http_client(token).get(clean_path, params=normalized_params)
        except httpx.TimeoutException as exc:
            raise PandaScoreTransportError("PandaScore request timed out") from exc
        except httpx.HTTPError as exc:
            raise PandaScoreTransportError("PandaScore request failed") from exc

        self._capture_rate_limit(response)
        if response.status_code in (401, 403):
            raise PandaScorePlanAccessError(
                response.status_code,
                clean_path,
                "token rejected or resource unavailable on the current plan",
            )
        if response.status_code == 429:
            raise PandaScoreHTTPStatusError(429, clean_path, "rate limit exceeded")
        if response.status_code >= 400:
            raise PandaScoreHTTPStatusError(
                response.status_code,
                clean_path,
                "upstream request returned an error",
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise PandaScoreTransportError("PandaScore returned a non-JSON response") from exc

        ttl_seconds = (
            self.default_cache_ttl_seconds if cache_ttl_seconds is None else cache_ttl_seconds
        )
        self._cache[cache_key] = (now + max(1, ttl_seconds), data)
        return data

    def cache_stats(self) -> dict[str, int]:
        return {"hits": self._cache_hits, "misses": self._cache_misses}

    def http_client(self, token: str | None = None) -> httpx.AsyncClient:
        auth_token = token or self._require_token()
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.request_timeout_seconds,
                headers={
                    "Authorization": f"Bearer {auth_token}",
                    "Accept": "application/json",
                },
            )
        return self._client

    def _capture_rate_limit(self, response: httpx.Response) -> None:
        value = response.headers.get("X-Rate-Limit-Remaining")
        try:
            self.last_rate_limit_remaining = int(value) if value is not None else None
        except ValueError:
            self.last_rate_limit_remaining = None

    def _normalize_params(self, params: dict[str, Any] | None) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in (params or {}).items():
            if value is None:
                continue
            if key == "page[size]":
                value = min(int(value), self.max_page_size)
            result[key] = value
        return result
