"""Complete PandaScore Team identity index and Provider-local cache contracts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.vnext.capabilities.esports.errors import EsportsInvalidArgumentsError, EsportsProviderError
from app.vnext.capabilities.esports.models import EsportsSearchRequest
from app.vnext.capabilities.esports.pandascore import PandaScoreEsportsProvider
from app.vnext.capabilities.esports.team_identity_index import TeamIdentityIndex
from app.vnext.providers.common import ProviderBatch
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter
from app.vnext.providers.pandascore.models import PandaScoreTeam

_NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)


class NoResolver:
    async def resolve_many_matches(self, matches):  # type: ignore[no-untyped-def]
        raise AssertionError("matches without games must not invoke the resolver")


class MutableClock:
    def __init__(self) -> None:
        self.value = _NOW

    def __call__(self) -> datetime:
        return self.value


def _team(identifier: int, name: str, acronym: str, slug: str) -> dict[str, object]:
    return {"id": identifier, "name": name, "acronym": acronym, "slug": slug}


def _team_match(team: dict[str, object]) -> dict[str, object]:
    return {
        "id": int(team["id"]) * 10,
        "name": f"{team['name']} fixture",
        "status": "finished",
        "opponents": [{"type": "Team", "opponent": team}],
        "games": [],
    }


def _provider(
    handler,  # type: ignore[no-untyped-def]
    *,
    clock: MutableClock | None = None,
    ttl: timedelta = timedelta(minutes=30),
) -> tuple[PandaScoreEsportsProvider, PandaScoreAdapter]:
    adapter = PandaScoreAdapter(
        base_url="https://pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    return (
        PandaScoreEsportsProvider(
            adapter,
            NoResolver(),  # type: ignore[arg-type]
            team_identity_index_ttl=ttl,
            clock=clock,
        ),
        adapter,
    )


def test_team_identity_index_keeps_distinct_candidates_and_deduplicates_one_team() -> None:
    repeated = PandaScoreTeam.model_validate(_team(1, "XG", "XG", "xg"))
    duplicate = PandaScoreTeam.model_validate(_team(2, "XG", "XG2", "xg-two"))

    index = TeamIdentityIndex.build([repeated, duplicate])

    assert [team.provider_id for team in index.lookup("xg")] == [1, 2]
    assert [team.provider_id for team in index.lookup("xg-two")] == [2]


def test_provider_reuses_one_complete_index_for_different_team_constraints() -> None:
    alpha = _team(1, "Alpha", "ALP", "alpha")
    beta = _team(2, "Beta", "BET", "beta")
    team_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/dota2/teams":
            page = int(request.url.params["page[number]"])
            team_pages.append(page)
            if page == 1:
                return httpx.Response(
                    200,
                    json=[alpha],
                    headers={
                        "Link": '<https://pandascore.test/dota2/teams?page[number]=2>; rel="next"'
                    },
                )
            return httpx.Response(200, json=[beta], headers={"X-Total": "2"})
        if request.url.path == "/teams/1/matches":
            return httpx.Response(200, json=[_team_match(alpha)], headers={"X-Total": "1"})
        if request.url.path == "/teams/2/matches":
            return httpx.Response(200, json=[_team_match(beta)], headers={"X-Total": "1"})
        raise AssertionError(request.url.path)

    provider, adapter = _provider(handler)

    async def exercise() -> list[int]:
        try:
            alpha_result = await provider.search(
                EsportsSearchRequest(kind="match", teams=["Alpha"])
            )
            beta_result = await provider.search(EsportsSearchRequest(kind="match", teams=["Beta"]))
            return [
                alpha_result.entities[0].source_identity,
                beta_result.entities[0].source_identity,
            ]
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == [10, 20]
    assert team_pages == [1, 2]


def test_expired_team_identity_index_rebuilds_once_and_never_uses_stale_data() -> None:
    alpha = _team(1, "Alpha", "ALP", "alpha")
    clock = MutableClock()
    team_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal team_requests
        if request.url.path == "/dota2/teams":
            team_requests += 1
            return httpx.Response(200, json=[alpha], headers={"X-Total": "1"})
        if request.url.path == "/teams/1/matches":
            return httpx.Response(200, json=[_team_match(alpha)], headers={"X-Total": "1"})
        raise AssertionError(request.url.path)

    provider, adapter = _provider(handler, clock=clock)

    async def exercise() -> None:
        try:
            await provider.search(EsportsSearchRequest(kind="match", teams=["Alpha"]))
            clock.value += timedelta(minutes=30)
            await provider.search(EsportsSearchRequest(kind="match", teams=["Alpha"]))
        finally:
            await adapter.aclose()

    asyncio.run(exercise())
    assert team_requests == 2


def test_expired_team_identity_refresh_failure_is_provider_error() -> None:
    alpha = _team(1, "Alpha", "ALP", "alpha")
    clock = MutableClock()
    team_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal team_requests
        if request.url.path == "/dota2/teams":
            team_requests += 1
            if team_requests == 1:
                return httpx.Response(200, json=[alpha], headers={"X-Total": "1"})
            return httpx.Response(503, json={"error": "unavailable"})
        if request.url.path == "/teams/1/matches":
            return httpx.Response(200, json=[_team_match(alpha)], headers={"X-Total": "1"})
        raise AssertionError(request.url.path)

    provider, adapter = _provider(handler, clock=clock)

    async def exercise() -> None:
        try:
            await provider.search(EsportsSearchRequest(kind="match", teams=["Alpha"]))
            clock.value += timedelta(minutes=30)
            await provider.search(EsportsSearchRequest(kind="match", teams=["Alpha"]))
        finally:
            await adapter.aclose()

    with pytest.raises(EsportsProviderError):
        asyncio.run(exercise())
    assert team_requests == 2


def test_incomplete_or_concurrent_team_index_builds_do_not_claim_identity() -> None:
    alpha = _team(1, "Alpha", "ALP", "alpha")
    beta = _team(2, "Beta", "BET", "beta")

    class UnknownPaginationAdapter:
        async def search_teams(self, **kwargs):  # type: ignore[no-untyped-def]
            return ProviderBatch(
                [PandaScoreTeam.model_validate(alpha)],
                _NOW,
                has_more=None,
            )

    incomplete_provider = PandaScoreEsportsProvider(
        UnknownPaginationAdapter(),  # type: ignore[arg-type]
        NoResolver(),  # type: ignore[arg-type]
    )

    with pytest.raises(EsportsProviderError):
        asyncio.run(
            incomplete_provider.search(EsportsSearchRequest(kind="match", teams=["Alpha"]))
        )

    team_pages: list[int] = []

    def concurrent_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/dota2/teams":
            page = int(request.url.params["page[number]"])
            team_pages.append(page)
            if page == 1:
                return httpx.Response(
                    200,
                    json=[alpha],
                    headers={
                        "Link": '<https://pandascore.test/dota2/teams?page[number]=2>; rel="next"'
                    },
                )
            return httpx.Response(200, json=[beta], headers={"X-Total": "2"})
        if request.url.path == "/teams/1/matches":
            return httpx.Response(200, json=[_team_match(alpha)], headers={"X-Total": "1"})
        if request.url.path == "/teams/2/matches":
            return httpx.Response(200, json=[_team_match(beta)], headers={"X-Total": "1"})
        raise AssertionError(request.url.path)

    provider, adapter = _provider(concurrent_handler)

    async def concurrent_exercise() -> None:
        try:
            await asyncio.gather(
                provider.search(EsportsSearchRequest(kind="match", teams=["Alpha"])),
                provider.search(EsportsSearchRequest(kind="match", teams=["Beta"])),
            )
        finally:
            await adapter.aclose()

    asyncio.run(concurrent_exercise())
    assert team_pages == [1, 2]


def test_cached_index_retains_existing_name_acronym_slug_and_ambiguity_contracts() -> None:
    xg = _team(1, "Xtreme Gaming", "XG", "xtreme-gaming")
    duplicate = _team(2, "XG", "XG2", "xg-two")
    team_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal team_requests
        if request.url.path == "/dota2/teams":
            team_requests += 1
            return httpx.Response(200, json=[xg, duplicate], headers={"X-Total": "2"})
        if request.url.path == "/teams/1/matches":
            return httpx.Response(200, json=[_team_match(xg)], headers={"X-Total": "1"})
        raise AssertionError(request.url.path)

    provider, adapter = _provider(handler)

    async def exercise() -> list[int]:
        try:
            by_name = await provider.search(
                EsportsSearchRequest(kind="match", teams=["Xtreme Gaming"])
            )
            by_slug = await provider.search(
                EsportsSearchRequest(kind="match", teams=["xtreme-gaming"])
            )
            await provider.search(EsportsSearchRequest(kind="match", teams=["XG"]))
            return [by_name.entities[0].source_identity, by_slug.entities[0].source_identity]
        finally:
            await adapter.aclose()

    with pytest.raises(EsportsInvalidArgumentsError) as exc_info:
        asyncio.run(exercise())
    assert exc_info.value.details["reason"] == "ambiguous"
    assert team_requests == 1
