import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CACHE_TTL = 3600
REQUEST_TIMEOUT_SECONDS = 20


class OpenDotaTransport:
    """Shared HTTP transport, cache, and request diagnostics for OpenDota."""

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._cache: dict[str, tuple[float, Any]] = {}
        self._client: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get(self, key: str, path: str) -> Any:
        started = time.perf_counter()
        now = time.monotonic()
        if key in self._cache:
            expires_at, data = self._cache[key]
            if now < expires_at:
                logger.info(
                    "OpenDota cache hit path=%s elapsed_ms=%s",
                    path,
                    round((time.perf_counter() - started) * 1000),
                )
                return data

        params = {"api_key": self.api_key} if self.api_key else None
        try:
            response = await self.http_client().get(path, params=params)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning(
                "OpenDota request failed path=%s elapsed_ms=%s type=%s error=%r",
                path,
                round((time.perf_counter() - started) * 1000),
                type(exc).__name__,
                exc,
            )
            raise

        self._cache[key] = (now + CACHE_TTL, data)
        logger.info(
            "OpenDota request completed path=%s status=%s elapsed_ms=%s",
            path,
            response.status_code,
            round((time.perf_counter() - started) * 1000),
        )
        return data

    def http_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        return self._client
