from __future__ import annotations

import httpx
import pytest

from app.integrations.pandascore.transport import (
    PandaScoreConfigurationError,
    PandaScoreHTTPStatusError,
    PandaScorePlanAccessError,
    PandaScoreTransport,
    PandaScoreTransportError,
)


def _transport(handler) -> PandaScoreTransport:
    transport = PandaScoreTransport(
        "https://api.pandascore.test",
        "test-token",
        max_page_size=10,
    )
    transport._client = httpx.AsyncClient(
        base_url=transport.base_url,
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer test-token"},
    )
    return transport


@pytest.mark.anyio
async def test_bearer_header_page_size_and_json() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["page_size"] = request.url.params.get("page[size]")
        return httpx.Response(
            200,
            json={"ok": True},
            request=request,
            headers={"X-Rate-Limit-Remaining": "42"},
        )

    transport = _transport(handler)
    try:
        assert await transport.get("/dota2/series", params={"page[size]": 100}) == {"ok": True}
        assert seen == {"authorization": "Bearer test-token", "page_size": "10"}
        assert transport.last_rate_limit_remaining == 42
    finally:
        await transport.aclose()


@pytest.mark.anyio
async def test_missing_token_is_configuration_error() -> None:
    transport = PandaScoreTransport("https://api.pandascore.test", None)
    with pytest.raises(PandaScoreConfigurationError, match="DOTAMIND_PANDASCORE_TOKEN"):
        await transport.get("/dota2/series")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, PandaScorePlanAccessError),
        (403, PandaScorePlanAccessError),
        (429, PandaScoreHTTPStatusError),
    ],
)
async def test_http_error_mapping_does_not_leak_token(status, error_type) -> None:
    secret = "test-token"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="upstream body with no credentials", request=request)

    transport = _transport(handler)
    try:
        with pytest.raises(error_type) as exc_info:
            await transport.get("/dota2/games/1")
        assert secret not in str(exc_info.value)
    finally:
        await transport.aclose()


@pytest.mark.anyio
async def test_non_json_and_timeout_are_transport_errors() -> None:
    def non_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json", request=request)

    transport = _transport(non_json)
    try:
        with pytest.raises(PandaScoreTransportError, match="non-JSON"):
            await transport.get("/dota2/series")
    finally:
        await transport.aclose()

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    transport = _transport(timeout)
    try:
        with pytest.raises(PandaScoreTransportError, match="timed out"):
            await transport.get("/dota2/series")
    finally:
        await transport.aclose()
