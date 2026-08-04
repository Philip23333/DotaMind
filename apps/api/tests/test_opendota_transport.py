import asyncio
import logging
import time

import httpx
import pytest

from app.integrations.opendota.heroes import OpenDotaHeroes
from app.integrations.opendota.teams import OpenDotaTeams
from app.integrations.opendota.transport import OpenDotaTransport


def test_transport_is_shared_across_team_endpoints_and_cache(caplog) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, json=[])

    async def exercise() -> tuple[httpx.AsyncClient, OpenDotaTransport]:
        transport = OpenDotaTransport("https://api.opendota.test")
        http_client = httpx.AsyncClient(
            base_url=transport.base_url,
            transport=httpx.MockTransport(handler),
        )
        transport._client = http_client
        teams = OpenDotaTeams(transport, OpenDotaHeroes(transport))

        await teams.get_all()
        await teams.get_players(2163)
        await teams.get_all()
        assert transport.http_client() is http_client
        return http_client, transport

    caplog.set_level(logging.INFO, logger="app.integrations.opendota")
    http_client, transport = asyncio.run(exercise())

    assert requests == ["/teams", "/teams/2163/players"]
    assert transport.cache_stats() == {"hits": 1, "misses": 2}
    assert "/teams" not in caplog.text

    asyncio.run(transport.aclose())
    assert http_client.is_closed
    assert transport._client is None


def test_transport_does_not_log_failed_path_or_raw_exception(caplog) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("upstream stalled", request=request)

    async def exercise() -> None:
        transport = OpenDotaTransport("https://api.opendota.test")
        transport._client = httpx.AsyncClient(
            base_url=transport.base_url,
            transport=httpx.MockTransport(handler),
        )
        teams = OpenDotaTeams(transport, OpenDotaHeroes(transport))
        try:
            with pytest.raises(httpx.ReadTimeout):
                await teams.get_players(2163)
        finally:
            await transport.aclose()

    caplog.set_level(logging.WARNING, logger="app.integrations.opendota")
    asyncio.run(exercise())

    assert "/teams/2163/players" not in caplog.text
    assert "ReadTimeout" not in caplog.text
    assert "upstream stalled" not in caplog.text


def test_match_details_use_long_lived_cache() -> None:
    async def exercise() -> float:
        transport = OpenDotaTransport("https://api.opendota.test")
        transport._client = httpx.AsyncClient(
            base_url=transport.base_url,
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"match_id": 123})
            ),
        )
        teams = OpenDotaTeams(
            transport,
            OpenDotaHeroes(transport),
            match_detail_cache_ttl_seconds=30 * 24 * 60 * 60,
        )
        try:
            await teams.get_match_detail(123)
            expires_at, _data = transport._cache["match_123"]
            return expires_at - time.monotonic()
        finally:
            await transport.aclose()

    remaining_ttl = asyncio.run(exercise())

    assert remaining_ttl > 29 * 24 * 60 * 60
