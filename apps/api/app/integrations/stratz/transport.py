import asyncio
import json
import logging
import time
from typing import Any
from urllib import error, request

logger = logging.getLogger(__name__)


class StratzTransport:
    """Shared GraphQL transport and diagnostics for STRATZ."""

    def __init__(
        self,
        graphql_url: str,
        token: str | None = None,
        *,
        request_timeout_seconds: float = 20,
        user_agent: str = "MetaMind/0.1",
        opener: Any | None = None,
    ) -> None:
        self.graphql_url = graphql_url
        self.token = token
        self.request_timeout_seconds = request_timeout_seconds
        self.user_agent = user_agent
        self._opener = opener

    async def aclose(self) -> None:
        return None

    async def graphql(
        self,
        operation_name: str,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        payload = {"query": query, "variables": variables or {}}
        try:
            response = await asyncio.to_thread(self._post, payload)
            if response.status_code >= 400:
                raise StratzHTTPStatusError(
                    operation_name,
                    response.status_code,
                    response.content_type,
                    response.body,
                )
            data = self._json(response, operation_name)
        except Exception as exc:
            logger.warning(
                "STRATZ request failed operation=%s elapsed_ms=%s type=%s error=%r",
                operation_name,
                round((time.perf_counter() - started) * 1000),
                type(exc).__name__,
                exc,
            )
            raise

        errors = data.get("errors")
        if errors:
            logger.warning(
                "STRATZ GraphQL errors operation=%s elapsed_ms=%s error_count=%s",
                operation_name,
                round((time.perf_counter() - started) * 1000),
                len(errors),
            )
            raise StratzGraphQLError(operation_name, errors)

        logger.info(
            "STRATZ request completed operation=%s status=%s elapsed_ms=%s",
            operation_name,
            response.status_code,
            round((time.perf_counter() - started) * 1000),
        )
        return data

    def _post(self, payload: dict[str, Any]) -> "_StratzHTTPResponse":
        encoded = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self.graphql_url,
            data=encoded,
            headers=self._headers(),
            method="POST",
        )
        try:
            response = self._urlopen(req)
            with response:
                return _StratzHTTPResponse(
                    status_code=response.status,
                    content_type=response.headers.get("content-type", ""),
                    body=response.read(),
                )
        except error.HTTPError as exc:
            return _StratzHTTPResponse(
                status_code=exc.code,
                content_type=exc.headers.get("content-type", ""),
                body=exc.read(),
            )

    def _urlopen(self, req: request.Request) -> Any:
        if self._opener is not None:
            return self._opener(req, timeout=self.request_timeout_seconds)
        return request.urlopen(req, timeout=self.request_timeout_seconds)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @staticmethod
    def _json(response: "_StratzHTTPResponse", operation_name: str) -> dict[str, Any]:
        try:
            data = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise StratzTransportError(
                operation_name,
                response.status_code,
                response.content_type,
            ) from exc
        if not isinstance(data, dict):
            raise StratzTransportError(
                operation_name,
                response.status_code,
                response.content_type,
            )
        return data


class _StratzHTTPResponse:
    def __init__(self, status_code: int, content_type: str, body: bytes) -> None:
        self.status_code = status_code
        self.content_type = content_type
        self.body = body


class StratzTransportError(RuntimeError):
    def __init__(
        self,
        operation_name: str,
        status_code: int,
        content_type: str,
    ) -> None:
        self.operation_name = operation_name
        self.status_code = status_code
        self.content_type = content_type
        super().__init__(
            f"STRATZ {operation_name} returned non-GraphQL response "
            f"status={status_code} content_type={content_type or 'unknown'}"
        )


class StratzHTTPStatusError(RuntimeError):
    def __init__(
        self,
        operation_name: str,
        status_code: int,
        content_type: str,
        body: bytes,
    ) -> None:
        self.operation_name = operation_name
        self.status_code = status_code
        self.content_type = content_type
        self.body = body
        super().__init__(
            f"STRATZ {operation_name} returned HTTP {status_code} "
            f"content_type={content_type or 'unknown'}"
        )


class StratzGraphQLError(RuntimeError):
    def __init__(self, operation_name: str, errors: list[dict[str, Any]]) -> None:
        self.operation_name = operation_name
        self.errors = errors
        messages = [
            str(error.get("message", "unknown GraphQL error")) for error in errors
        ]
        super().__init__(f"STRATZ GraphQL {operation_name} failed: {'; '.join(messages)}")
