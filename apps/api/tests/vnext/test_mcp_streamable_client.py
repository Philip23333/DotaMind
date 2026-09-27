from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from mcp import Client
from mcp.server import MCPServer

from app.vnext.integrations.mcp import MCPRemoteClient, MCPRemoteError


def _tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=f"Remote {name}",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        output_schema=None,
    )


def test_official_mcp_sdk_discovers_and_calls_a_real_protocol_tool() -> None:
    server = MCPServer("tavily-test")
    observed: list[tuple[str, int]] = []

    @server.tool(name="tavily_search", description="Search fixture")
    def search(query: str, max_results: int = 3) -> str:
        observed.append((query, max_results))
        return json.dumps({"results": [{"title": "Fixture", "url": "https://example.test"}]})

    sessions = {"opened": 0, "closed": 0}

    @asynccontextmanager
    async def client_context():
        sessions["opened"] += 1
        async with Client(server, mode="legacy") as client:
            try:
                yield client
            finally:
                sessions["closed"] += 1

    remote = MCPRemoteClient(
        url="https://mcp.tavily.com/mcp",
        api_key="test-key-only",
        timeout_seconds=2,
        client_context_factory=client_context,
    )

    async def run() -> tuple[list[Any], Any]:
        tools = await remote.list_tools()
        result = await remote.call_tool(
            "tavily_search",
            {"query": "synthetic test", "max_results": 2},
        )
        return tools, result

    tools, result = asyncio.run(asyncio.wait_for(run(), timeout=5))

    assert [tool.name for tool in tools] == ["tavily_search"]
    assert tools[0].input_schema["properties"]["query"]["type"] == "string"
    assert observed == [("synthetic test", 2)]
    assert result.is_error is False
    assert "https://example.test" in result.content[0].text
    assert sessions == {"opened": 2, "closed": 2}


def test_tool_discovery_follows_mcp_pagination_and_uses_a_new_session_per_operation() -> None:
    created: list[Any] = []

    class FakeSession:
        def __init__(self, pages: list[Any]) -> None:
            self.pages = pages
            self.cursors: list[str | None] = []
            self.closed = False

        async def list_tools(self, *, cursor: str | None = None) -> Any:
            self.cursors.append(cursor)
            return self.pages[len(self.cursors) - 1]

        async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
            return {"name": name, "arguments": arguments}

    @asynccontextmanager
    async def client_context():
        if not created:
            session = FakeSession(
                [
                    SimpleNamespace(tools=[_tool("first")], next_cursor="page-2"),
                    SimpleNamespace(tools=[_tool("second")], next_cursor=None),
                ]
            )
        else:
            session = FakeSession([])
        created.append(session)
        try:
            yield session
        finally:
            session.closed = True

    remote = MCPRemoteClient(
        url="https://mcp.tavily.com/mcp",
        api_key="test-key-only",
        timeout_seconds=2,
        client_context_factory=client_context,
    )
    tools = asyncio.run(remote.list_tools())
    result = asyncio.run(remote.call_tool("tavily_search", {"query": "query"}))

    assert [tool.name for tool in tools] == ["first", "second"]
    assert created[0].cursors == [None, "page-2"]
    assert result == {"name": "tavily_search", "arguments": {"query": "query"}}
    assert len(created) == 2
    assert all(session.closed for session in created)


def test_production_transport_uses_bearer_header_and_closes_both_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx2
    import mcp
    import mcp.client.streamable_http as streamable_http

    captured: dict[str, Any] = {"http_open": 0, "http_close": 0, "mcp_open": 0, "mcp_close": 0}

    class FakeHTTPContext:
        def __init__(self, *, headers: dict[str, str], timeout: Any) -> None:
            captured["headers"] = headers
            captured["timeout"] = timeout

        async def __aenter__(self) -> FakeHTTPContext:
            captured["http_open"] += 1
            return self

        async def __aexit__(self, *args: Any) -> None:
            captured["http_close"] += 1

    class FakeMCPClient:
        def __init__(self, transport: Any, **kwargs: Any) -> None:
            captured["transport"] = transport
            captured["client_options"] = kwargs

        async def __aenter__(self) -> FakeMCPClient:
            captured["mcp_open"] += 1
            return self

        async def __aexit__(self, *args: Any) -> None:
            captured["mcp_close"] += 1

        async def list_tools(self, *, cursor: str | None = None) -> Any:
            return SimpleNamespace(tools=[], next_cursor=None)

        async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
            return {"tool": name, "arguments": arguments}

    def fake_transport(url: str, *, http_client: Any) -> object:
        captured["url"] = url
        captured["http_client"] = http_client
        return object()

    monkeypatch.setattr(httpx2, "AsyncClient", FakeHTTPContext)
    monkeypatch.setattr(mcp, "Client", FakeMCPClient)
    monkeypatch.setattr(streamable_http, "streamable_http_client", fake_transport)
    remote = MCPRemoteClient(
        url="https://mcp.tavily.com/mcp",
        api_key="header-only-secret",
        timeout_seconds=2,
    )

    async def run() -> None:
        assert await remote.list_tools() == []
        assert await remote.call_tool("tavily_search", {"query": "test"}) == {
            "tool": "tavily_search",
            "arguments": {"query": "test"},
        }

    asyncio.run(asyncio.wait_for(run(), timeout=5))

    assert captured["url"] == "https://mcp.tavily.com/mcp"
    assert captured["headers"] == {"Authorization": "Bearer header-only-secret"}
    assert captured["client_options"] == {
        "mode": "legacy",
        "read_timeout_seconds": 2,
        "cache": None,
    }
    assert captured["http_open"] == captured["http_close"] == 2
    assert captured["mcp_open"] == captured["mcp_close"] == 2


def test_mcp_endpoint_rejects_credentials_in_url() -> None:
    with pytest.raises(ValueError, match="contain no credentials or query") as raised:
        MCPRemoteClient(
            url="https://mcp.tavily.com/mcp?tavilyApiKey=unsafe-marker",
            api_key="test-key-only",
            timeout_seconds=2,
        )
    assert "unsafe-marker" not in str(raised.value)


def test_timeout_and_cancellation_close_the_mcp_session() -> None:
    async def exercise_cancel() -> None:
        entered = asyncio.Event()
        closed = asyncio.Event()

        class WaitingSession:
            async def list_tools(self, *, cursor: str | None = None) -> Any:
                entered.set()
                await asyncio.Event().wait()

            async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
                raise AssertionError("not used")

        @asynccontextmanager
        async def client_context():
            try:
                yield WaitingSession()
            finally:
                closed.set()

        remote = MCPRemoteClient(
            url="https://mcp.tavily.com/mcp",
            api_key="test-key-only",
            timeout_seconds=2,
            client_context_factory=client_context,
        )
        task = asyncio.create_task(remote.list_tools())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()

    async def exercise_timeout() -> None:
        closed = asyncio.Event()

        class WaitingSession:
            async def list_tools(self, *, cursor: str | None = None) -> Any:
                await asyncio.Event().wait()

            async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
                raise AssertionError("not used")

        @asynccontextmanager
        async def client_context():
            try:
                yield WaitingSession()
            finally:
                closed.set()

        remote = MCPRemoteClient(
            url="https://mcp.tavily.com/mcp",
            api_key="test-key-only",
            timeout_seconds=0.02,
            client_context_factory=client_context,
        )
        with pytest.raises(MCPRemoteError) as raised:
            await remote.list_tools()
        assert raised.value.category == "timeout"
        assert closed.is_set()

    asyncio.run(asyncio.wait_for(exercise_cancel(), timeout=3))
    asyncio.run(asyncio.wait_for(exercise_timeout(), timeout=3))
