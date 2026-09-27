"""Small authenticated HTTP client for OpenDota's existing match endpoint."""

from __future__ import annotations

import math
from typing import Any

import httpx


class OpenDotaError(RuntimeError):
    """Base class for sanitized OpenDota failures."""


class OpenDotaTimeoutError(OpenDotaError):
    def __init__(self) -> None:
        super().__init__("OpenDota request timed out")


class OpenDotaTransportError(OpenDotaError):
    def __init__(self) -> None:
        super().__init__("OpenDota transport request failed")


class OpenDotaHTTPError(OpenDotaError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__("OpenDota request failed with an HTTP status")


class OpenDotaResponseError(OpenDotaError):
    def __init__(self) -> None:
        super().__init__("OpenDota returned a non-JSON response")


class OpenDotaClient:
    """Fetch one match and always close the per-request HTTP resources."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.opendota.com/api",
        api_key: str = "",
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("OpenDota timeout must be a finite positive number")
        try:
            parsed_url = httpx.URL(base_url)
        except (TypeError, ValueError):
            raise ValueError("OpenDota base URL must be an absolute HTTP(S) URL") from None
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.host
            or parsed_url.username
            or parsed_url.password
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError("OpenDota base URL must not contain credentials or query data")
        self.base_url = str(parsed_url).rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(base_url={self.base_url!r}, api_key=<redacted>, "
            f"timeout_seconds={self.timeout_seconds!r})"
        )

    async def get_match(self, valve_game_id: int) -> Any:
        params = {"api_key": self.api_key} if self.api_key else None
        try:
            async with httpx.AsyncClient(
                base_url=f"{self.base_url}/",
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.get(f"matches/{valve_game_id}", params=params)
        except httpx.TimeoutException:
            raise OpenDotaTimeoutError() from None
        except httpx.RequestError:
            raise OpenDotaTransportError() from None

        if not 200 <= response.status_code < 300:
            raise OpenDotaHTTPError(response.status_code)
        try:
            return response.json()
        except (ValueError, UnicodeDecodeError):
            raise OpenDotaResponseError() from None


__all__ = [
    "OpenDotaClient",
    "OpenDotaError",
    "OpenDotaHTTPError",
    "OpenDotaResponseError",
    "OpenDotaTimeoutError",
    "OpenDotaTransportError",
]
