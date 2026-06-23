import asyncio
import json
import logging
from email.message import Message

import pytest

from app.integrations.stratz import StratzClient
from app.integrations.stratz.transport import (
    StratzGraphQLError,
    StratzHTTPStatusError,
    StratzTransport,
    StratzTransportError,
)


class FakeHTTPResponse:
    def __init__(
        self,
        status: int,
        body: dict | str,
        *,
        content_type: str = "application/json",
    ) -> None:
        self.status = status
        self.headers = Message()
        self.headers["content-type"] = content_type
        if isinstance(body, str):
            self._body = body.encode("utf-8")
        else:
            self._body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_stratz_transport_sends_bearer_token_without_logging_it(caplog) -> None:
    requests = []

    def opener(req, *, timeout: float) -> FakeHTTPResponse:
        requests.append((req, timeout))
        return FakeHTTPResponse(200, {"data": {"ok": True}})

    async def exercise() -> None:
        transport = StratzTransport(
            "https://api.stratz.test/graphql",
            "secret-token",
            opener=opener,
        )
        try:
            await transport.graphql("TestOperation", "query { ok }")
        finally:
            await transport.aclose()

    caplog.set_level(logging.INFO, logger="app.integrations.stratz")
    asyncio.run(exercise())

    req, timeout = requests[0]
    assert timeout == 20
    assert req.headers["Authorization"] == "Bearer secret-token"
    assert req.headers["User-agent"] == "MetaMind/0.1"
    assert json.loads(req.data.decode("utf-8")) == {
        "query": "query { ok }",
        "variables": {},
    }
    assert "secret-token" not in caplog.text
    assert "STRATZ request completed operation=TestOperation" in caplog.text


def test_stratz_transport_raises_graphql_errors() -> None:
    def opener(_req, *, timeout: float) -> FakeHTTPResponse:
        return FakeHTTPResponse(200, {"errors": [{"message": "bad query"}]})

    async def exercise() -> None:
        transport = StratzTransport(
            "https://api.stratz.test/graphql",
            "secret-token",
            opener=opener,
        )
        try:
            with pytest.raises(StratzGraphQLError) as raised:
                await transport.graphql("BadOperation", "query { bad }")
        finally:
            await transport.aclose()
        assert raised.value.operation_name == "BadOperation"
        assert "bad query" in str(raised.value)

    asyncio.run(exercise())


def test_stratz_transport_rejects_non_json_response() -> None:
    def opener(_req, *, timeout: float) -> FakeHTTPResponse:
        return FakeHTTPResponse(200, "<html>blocked</html>", content_type="text/html")

    async def exercise() -> None:
        transport = StratzTransport(
            "https://api.stratz.test/graphql",
            "secret-token",
            opener=opener,
        )
        try:
            with pytest.raises(StratzTransportError) as raised:
                await transport.graphql("BlockedOperation", "query { blocked }")
        finally:
            await transport.aclose()
        assert raised.value.operation_name == "BlockedOperation"
        assert raised.value.content_type == "text/html"

    asyncio.run(exercise())


def test_stratz_transport_raises_http_status_errors() -> None:
    def opener(_req, *, timeout: float) -> FakeHTTPResponse:
        return FakeHTTPResponse(
            403,
            {"message": "A bearer token is required"},
            content_type="application/json",
        )

    async def exercise() -> None:
        transport = StratzTransport(
            "https://api.stratz.test/graphql",
            "secret-token",
            opener=opener,
        )
        with pytest.raises(StratzHTTPStatusError) as raised:
            await transport.graphql("ForbiddenOperation", "query { blocked }")
        assert raised.value.status_code == 403
        assert raised.value.content_type == "application/json"

    asyncio.run(exercise())


def test_stratz_client_alias_uses_transport() -> None:
    assert issubclass(StratzClient, StratzTransport)
