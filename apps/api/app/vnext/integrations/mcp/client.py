"""Per-operation MCP client sessions over Streamable HTTP."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from math import isfinite
from typing import Any, Protocol, TypeVar
from urllib.parse import urlsplit

_T = TypeVar("_T")
_MAX_TOOL_LIST_PAGES = 100


@dataclass(frozen=True, slots=True)
class DiscoveredMCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None


class MCPRemoteError(RuntimeError):
    """Sanitized transport or protocol failure without provider response text."""

    def __init__(self, category: str, status_code: int | None = None) -> None:
        super().__init__("remote MCP request failed")
        self.category = category
        self.status_code = status_code


class MCPClientSession(Protocol):
    async def list_tools(self, *, cursor: str | None = None) -> Any: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


MCPClientContextFactory = Callable[[], AbstractAsyncContextManager[MCPClientSession]]


class MCPRemoteClient:
    """Open and close a fresh authenticated MCP session for each operation."""

    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        timeout_seconds: float,
        client_context_factory: MCPClientContextFactory | None = None,
    ) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("MCP endpoint must be HTTPS and contain no credentials or query")
        if not api_key.strip():
            raise ValueError("MCP API key is required")
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("MCP timeout must be a finite positive number")
        self._url = url
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._client_context_factory = client_context_factory

    async def list_tools(self) -> list[DiscoveredMCPTool]:
        async def discover(client: MCPClientSession) -> list[DiscoveredMCPTool]:
            discovered: list[DiscoveredMCPTool] = []
            cursor: str | None = None
            seen_cursors: set[str] = set()
            for _ in range(_MAX_TOOL_LIST_PAGES):
                page = await client.list_tools(cursor=cursor)
                for tool in page.tools:
                    input_schema = getattr(tool, "input_schema", None)
                    if not isinstance(input_schema, Mapping):
                        raise MCPRemoteError("protocol")
                    output_schema = getattr(tool, "output_schema", None)
                    if output_schema is not None and not isinstance(output_schema, Mapping):
                        raise MCPRemoteError("protocol")
                    discovered.append(
                        DiscoveredMCPTool(
                            name=str(tool.name),
                            description=str(getattr(tool, "description", "") or ""),
                            input_schema=dict(input_schema),
                            output_schema=(
                                dict(output_schema) if output_schema is not None else None
                            ),
                        )
                    )
                next_cursor = getattr(page, "next_cursor", None)
                if next_cursor is None:
                    return discovered
                if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
                    raise MCPRemoteError("protocol")
                seen_cursors.add(next_cursor)
                cursor = next_cursor
            raise MCPRemoteError("protocol")

        return await self._run(discover)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return await self._run(lambda client: client.call_tool(name, arguments))

    async def _run(self, operation: Callable[[MCPClientSession], Awaitable[_T]]) -> _T:
        try:
            return await asyncio.wait_for(self._run_connected(operation), self._timeout_seconds)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            raise MCPRemoteError("timeout") from None
        except MCPRemoteError:
            raise
        except Exception as exc:
            status_code = _http_status_code(exc)
            category = "http" if status_code is not None else _exception_category(exc)
            raise MCPRemoteError(category, status_code) from None

    async def _run_connected(
        self,
        operation: Callable[[MCPClientSession], Awaitable[_T]],
    ) -> _T:
        async with self._client_context() as client:
            return await operation(client)

    @asynccontextmanager
    async def _client_context(self) -> AsyncIterator[MCPClientSession]:
        if self._client_context_factory is not None:
            async with self._client_context_factory() as client:
                yield client
            return

        import httpx2
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client

        headers = {"Authorization": f"Bearer {self._api_key}"}
        timeout = httpx2.Timeout(self._timeout_seconds)
        async with httpx2.AsyncClient(headers=headers, timeout=timeout) as http_client:
            transport = streamable_http_client(self._url, http_client=http_client)
            async with Client(
                transport,
                mode="legacy",
                read_timeout_seconds=self._timeout_seconds,
                cache=None,
            ) as client:
                yield client


def _http_status_code(error: Exception) -> int | None:
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    return status_code if isinstance(status_code, int) and 100 <= status_code <= 599 else None


def _exception_category(error: Exception) -> str:
    if type(error).__name__ in {"MCPError", "JSONRPCError", "ValidationError"}:
        return "protocol"
    return "transport"


__all__ = ["DiscoveredMCPTool", "MCPRemoteClient", "MCPRemoteError"]
