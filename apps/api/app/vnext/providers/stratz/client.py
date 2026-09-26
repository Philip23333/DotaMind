"""Small, per-request HTTPX client for the STRATZ GraphQL API."""

from __future__ import annotations

import math
from typing import Any

import httpx


class StratzError(RuntimeError):
    """Base class for sanitized STRATZ failures."""


class StratzTimeoutError(StratzError):
    def __init__(self) -> None:
        super().__init__("STRATZ request timed out")


class StratzHTTPError(StratzError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__("STRATZ request failed with an HTTP status")


class StratzTransportError(StratzError):
    def __init__(self) -> None:
        super().__init__("STRATZ transport request failed")


class StratzResponseError(StratzError):
    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__("STRATZ returned an invalid GraphQL response")


class StratzGraphQLError(StratzError):
    def __init__(self) -> None:
        super().__init__("STRATZ GraphQL request returned errors")


class StratzGraphQLClient:
    """Issue one authenticated GraphQL request and close its HTTP resources."""

    def __init__(
        self,
        *,
        graphql_url: str,
        token: str,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("STRATZ timeout must be a finite positive number")
        if not token.strip():
            raise ValueError("STRATZ token is required")
        self.graphql_url = graphql_url
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def graphql(
        self,
        query: str,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "STRATZ_API",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    self.graphql_url,
                    json={"query": query, "variables": variables},
                    headers=headers,
                )
        except httpx.TimeoutException:
            raise StratzTimeoutError() from None
        except httpx.RequestError:
            raise StratzTransportError() from None

        if not 200 <= response.status_code < 300:
            raise StratzHTTPError(response.status_code)

        try:
            payload = response.json()
        except (ValueError, UnicodeDecodeError):
            raise StratzResponseError("response") from None
        if not isinstance(payload, dict):
            raise StratzResponseError("response")

        errors = payload.get("errors")
        if errors is not None and not isinstance(errors, list):
            raise StratzResponseError("errors")
        if errors:
            raise StratzGraphQLError()
        return payload


__all__ = [
    "StratzError",
    "StratzGraphQLError",
    "StratzGraphQLClient",
    "StratzHTTPError",
    "StratzResponseError",
    "StratzTimeoutError",
    "StratzTransportError",
]
