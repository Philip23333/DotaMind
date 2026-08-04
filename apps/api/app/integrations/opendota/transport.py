import time
from typing import Any

import httpx


class OpenDotaTransport:
    """Shared HTTP transport, cache, and request diagnostics for OpenDota."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        request_timeout_seconds: float = 20,
        default_cache_ttl_seconds: int = 3600,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.request_timeout_seconds = request_timeout_seconds
        self.default_cache_ttl_seconds = default_cache_ttl_seconds
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._client: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get(
        self,
        key: str,
        path: str,
        *,
        cache_ttl_seconds: int | None = None,
    ) -> Any:
        now = time.monotonic()
        if key in self._cache:
            expires_at, data = self._cache[key]
            if now < expires_at:
                self._cache_hits += 1
                return data

        self._cache_misses += 1
        params = {"api_key": self.api_key} if self.api_key else None
        try:
            response = await self.http_client().get(path, params=params)
            response.raise_for_status()
            data = response.json()
        except Exception:
            raise

        ttl_seconds = cache_ttl_seconds or self.default_cache_ttl_seconds
        self._cache[key] = (now + ttl_seconds, data)
        return data

    def cache_stats(self) -> dict[str, int]:
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
        }

    def http_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.request_timeout_seconds,
            )
        return self._client
