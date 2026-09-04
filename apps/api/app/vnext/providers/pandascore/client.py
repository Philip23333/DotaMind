"""Minimal PandaScore HTTP client for collection requests."""

from __future__ import annotations

from typing import Any

import httpx


class PandaScoreConfigurationError(RuntimeError):
    """Raised when the client cannot authenticate a request."""


class PandaScoreProtocolError(RuntimeError):
    """Raised when a collection endpoint returns an unexpected payload."""


class PandaScoreClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def get_list(
        self,
        path: str,
        *,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not self.token:
            raise PandaScoreConfigurationError("PandaScore token is not configured")

        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
            },
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = await client.get(path, params=params)
            response.raise_for_status()
            payload = response.json()

        if not isinstance(payload, list):
            raise PandaScoreProtocolError(
                "PandaScore collection response must be a JSON list"
            )

        return [item for item in payload if isinstance(item, dict)]


__all__ = [
    "PandaScoreClient",
    "PandaScoreConfigurationError",
    "PandaScoreProtocolError",
]
