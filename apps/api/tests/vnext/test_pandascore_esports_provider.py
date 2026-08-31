"""Provider-level tests with inline PandaScore payloads and MockTransport."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app.vnext.artifacts import ArtifactReader, MemoryArtifactStore
from app.vnext.capabilities.esports.errors import EsportsInvalidArgumentsError
from app.vnext.capabilities.esports.models import EsportsSearchRequest
from app.vnext.capabilities.esports.pandascore import PandaScoreEsportsProvider
from app.vnext.capabilities.esports.service import EsportsSearchService
from app.vnext.domain.matches.resolution import ResolutionDecision
from app.vnext.providers.opendota.adapter import (
    OpenDotaConfigurationError,
    OpenDotaSchemaError,
    OpenDotaTimeoutError,
)
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter


class NoResolver:
    async def resolve_many(self, match, games):  # type: ignore[no-untyped-def]
        raise AssertionError("matches without games must not invoke the resolver")


def _team(identifier: int, name: str) -> dict[str, object]:
    return {"id": identifier, "name": name, "acronym": name[:3].upper(), "slug": name.lower()}


def _match(
    identifier: int,
    *,
    name: str,
    status: str = "finished",
    end_at: str = "2026-08-20T10:00:00Z",
    teams: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "id": identifier,
        "name": name,
        "status": status,
        "scheduled_at": "2026-08-20T08:00:00Z",
        "begin_at": "2026-08-20T08:05:00Z",
        "end_at": end_at,
        "opponents": [{"type": "Team", "opponent": team} for team in teams or []],
        "games": [],
    }


def _adapter(handler) -> PandaScoreAdapter:  # type: ignore[no-untyped-def]
    return PandaScoreAdapter(
        base_url="https://pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )


def test_all_esports_kinds_use_one_provider_contract_and_allowed_discovery_endpoints() -> None:
    calls: list[str] = []
    payloads = {
        "/dota2/leagues": [{"id": 1, "name": "The International"}],
        "/dota2/series/past": [
            {
                "id": 2,
                "name": "The International",
                "status": "finished",
                "end_at": "2026-08-23T00:00:00Z",
            }
        ],
        "/dota2/tournaments/running": [
            {"id": 3, "name": "Playoffs", "status": "running", "begin_at": "2026-08-22T00:00:00Z"}
        ],
        "/dota2/matches/past": [_match(4, name="Grand final")],
        "/dota2/teams": [_team(5, "Team Spirit")],
        "/dota2/players": [{"id": 6, "name": "Yatoro"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert "search[name]" not in request.url.params
        return httpx.Response(200, json=payloads[request.url.path], headers={"X-Total": "1"})

    adapter = _adapter(handler)
    provider = PandaScoreEsportsProvider(adapter, NoResolver())  # type: ignore[arg-type]

    async def exercise() -> list[str]:
        requests = [
            EsportsSearchRequest(kind="league", query="International"),
            EsportsSearchRequest(kind="series", time_scope="past"),
            EsportsSearchRequest(kind="tournament", time_scope="running"),
            EsportsSearchRequest(kind="match", time_scope="past"),
            EsportsSearchRequest(kind="team", query="Spirit"),
            EsportsSearchRequest(kind="player", query="Yatoro"),
        ]
        try:
            batches = [await provider.search(request) for request in requests]
        finally:
            await adapter.aclose()
        return [batch.entities[0].kind for batch in batches]

    assert asyncio.run(exercise()) == [
        "league",
        "series",
        "tournament",
        "match",
        "team",
        "player",
    ]
    assert calls == [
        "/dota2/leagues",
        "/dota2/series/past",
        "/dota2/tournaments/running",
        "/dota2/matches/past",
        "/dota2/teams",
        "/dota2/players",
    ]
    assert not any(path.startswith("/dota2/games/") or path.endswith("/games") for path in calls)


def test_past_match_search_over_fetches_orders_by_event_time_and_marks_truncation() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        page = request.url.params.get("page[number]")
        if page == "1":
            return httpx.Response(
                200,
                json=[_match(1, name="Older", end_at="2026-08-20T10:00:00Z")],
                headers={
                    "Link": (
                        '<https://pandascore.test/dota2/matches/past?page[number]=2>; rel="next"'
                    )
                },
            )
        return httpx.Response(
            200,
            json=[_match(2, name="Newer", end_at="2026-08-21T10:00:00Z")],
            headers={"X-Total": "2"},
        )

    adapter = _adapter(handler)
    provider = PandaScoreEsportsProvider(adapter, NoResolver())  # type: ignore[arg-type]

    async def exercise():
        try:
            return await provider.search(
                EsportsSearchRequest(kind="match", time_scope="past", limit=1)
            )
        finally:
            await adapter.aclose()

    batch = asyncio.run(exercise())

    assert [entity.document["name"] for entity in batch.entities] == ["Newer", "Older"]
    assert batch.truncated is True
    assert len(calls) == 2


def test_match_team_constraints_use_exact_identity_and_and_semantics() -> None:
    alpha = _team(11, "Alpha")
    beta = _team(12, "Beta")
    gamma = _team(13, "Gamma")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/dota2/teams":
            assert "search[name]" not in request.url.params
            return httpx.Response(200, json=[alpha, beta], headers={"X-Total": "2"})
        if request.url.path == "/teams/11/matches":
            return httpx.Response(
                200,
                json=[
                    _match(20, name="Alpha vs Gamma", teams=[alpha, gamma]),
                    _match(21, name="Alpha vs Beta", teams=[alpha, beta]),
                ],
                headers={"X-Total": "2"},
            )
        raise AssertionError(request.url.path)

    adapter = _adapter(handler)
    provider = PandaScoreEsportsProvider(adapter, NoResolver())  # type: ignore[arg-type]

    async def exercise():
        try:
            return await provider.search(
                EsportsSearchRequest(kind="match", teams=["Alpha", "Beta"], time_scope="past")
            )
        finally:
            await adapter.aclose()

    batch = asyncio.run(exercise())

    assert [entity.source_identity for entity in batch.entities] == [21]


class RecordingResolver:
    def __init__(self) -> None:
        self.calls = 0

    async def resolve_many(self, match, games):  # type: ignore[no-untyped-def]
        self.calls += 1
        assert len(games) == 2
        return [
            ResolutionDecision(status="resolved", resolved_provider_match_id=9001),
            ResolutionDecision(status="not_found"),
        ]


def test_match_enrichment_preserves_source_games_and_adds_per_game_resolution() -> None:
    raw_match = _match(
        30,
        name="Grand final",
        teams=[_team(11, "Alpha"), _team(12, "Beta")],
    )
    raw_match["serie"] = {"id": 99, "name": "The International", "year": 2026}
    raw_match["games"] = [
        {
            "id": 301,
            "position": 1,
            "status": "finished",
            "begin_at": "2026-08-20T08:05:00Z",
            "end_at": "2026-08-20T08:45:00Z",
            "length": 2400,
            "winner": {"id": 11},
            "provider_extra": "kept",
        },
        {
            "id": 302,
            "position": 2,
            "status": "finished",
            "begin_at": "2026-08-20T09:05:00Z",
            "end_at": "2026-08-20T09:45:00Z",
            "length": 2400,
            "winner": {"id": 12},
        },
    ]

    class InlineAdapter:
        async def list_matches(self, **kwargs):  # type: ignore[no-untyped-def]
            from app.vnext.providers.common import ProviderBatch
            from app.vnext.providers.pandascore.models import PandaScoreMatch

            return ProviderBatch(
                [PandaScoreMatch.model_validate(raw_match)],
                datetime(2026, 8, 30, tzinfo=timezone.utc),
                has_more=False,
            )

    resolver = RecordingResolver()
    provider = PandaScoreEsportsProvider(InlineAdapter(), resolver)  # type: ignore[arg-type]
    batch = asyncio.run(provider.search(EsportsSearchRequest(kind="match", time_scope="past")))

    games = batch.entities[0].document["games"]
    assert resolver.calls == 1
    assert games[0]["provider_extra"] == "kept"
    assert games[0]["valve_game_id"] == 9001
    assert games[0]["resolution"] == "resolved"
    assert games[1]["valve_game_id"] is None
    assert games[1]["resolution"] == "not_found"


def test_match_search_externalizes_full_enriched_document_for_artifact_read() -> None:
    raw_match = _match(40, name="Artifact match", teams=[_team(11, "Alpha")])
    raw_match["games"] = [
        {
            "id": 401,
            "position": 1,
            "status": "finished",
            "begin_at": "2026-08-20T08:05:00Z",
            "end_at": "2026-08-20T08:45:00Z",
            "length": 2400,
            "winner": {"id": 11},
            "provider_extra": "preserved-in-artifact",
        },
        {
            "id": 402,
            "position": 2,
            "status": "finished",
            "begin_at": "2026-08-20T09:05:00Z",
            "end_at": "2026-08-20T09:45:00Z",
            "length": 2400,
            "winner": {"id": 11},
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/dota2/matches/past"
        return httpx.Response(200, json=[raw_match], headers={"X-Total": "1"})

    adapter = _adapter(handler)
    resolver = RecordingResolver()
    store = MemoryArtifactStore()
    service = EsportsSearchService(
        PandaScoreEsportsProvider(adapter, resolver),
        store,
    )

    async def exercise():
        try:
            result = await service.search(EsportsSearchRequest(kind="match", time_scope="past"))
            artifact = await ArtifactReader(store).read(
                result.records[0].artifact_ref,
                "facts.games",
            )
            return result, artifact
        finally:
            await adapter.aclose()

    result, artifact = asyncio.run(exercise())

    assert result.records[0].facts["sections"]["games"] == {"kind": "collection", "count": 2}
    assert resolver.calls == 1
    assert artifact.value[0]["provider_extra"] == "preserved-in-artifact"
    assert artifact.value[0]["valve_game_id"] == 9001
    assert artifact.value[0]["resolution"] == "resolved"
    assert artifact.value[1]["valve_game_id"] is None
    assert artifact.value[1]["resolution"] == "not_found"


def test_dedicated_lifecycle_endpoints_do_not_apply_status_filtering() -> None:
    payloads = {
        "/dota2/series/upcoming": [{"id": 51, "name": "Upcoming series", "status": "not_started"}],
        "/dota2/tournaments/running": [{"id": 52, "name": "Running tournament"}],
        "/dota2/matches/upcoming": [_match(53, name="Upcoming match", status="not_started")],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payloads[request.url.path], headers={"X-Total": "1"})

    adapter = _adapter(handler)
    provider = PandaScoreEsportsProvider(adapter, NoResolver())  # type: ignore[arg-type]

    async def exercise() -> list[int]:
        try:
            requests = [
                EsportsSearchRequest(kind="series", time_scope="upcoming"),
                EsportsSearchRequest(kind="tournament", time_scope="running"),
                EsportsSearchRequest(kind="match", time_scope="upcoming"),
            ]
            batches = [await provider.search(request) for request in requests]
            return [batch.entities[0].source_identity for batch in batches]
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == [51, 52, 53]


def test_match_query_uses_full_document_without_native_name_prefilter() -> None:
    raw_match = _match(61, name="Grand final: VSN vs TS")
    raw_match["league"] = {"id": 1, "name": "The International"}
    raw_match["serie"] = {"id": 2, "full_name": "The International 2026"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/dota2/matches/past"
        assert "search[name]" not in request.url.params
        return httpx.Response(200, json=[raw_match], headers={"X-Total": "1"})

    adapter = _adapter(handler)
    provider = PandaScoreEsportsProvider(adapter, NoResolver())  # type: ignore[arg-type]

    async def exercise():
        try:
            return await provider.search(
                EsportsSearchRequest(
                    kind="match",
                    time_scope="past",
                    query="The International 2026",
                )
            )
        finally:
            await adapter.aclose()

    batch = asyncio.run(exercise())
    assert [entity.source_identity for entity in batch.entities] == [61]


def test_team_relationship_matches_use_local_lifecycle_filtering() -> None:
    alpha = _team(71, "Alpha")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/dota2/teams":
            return httpx.Response(200, json=[alpha], headers={"X-Total": "1"})
        if request.url.path == "/teams/71/matches":
            return httpx.Response(
                200,
                json=[_match(72, name="Alpha upcoming", status="not_started", teams=[alpha])],
                headers={"X-Total": "1"},
            )
        raise AssertionError(request.url.path)

    adapter = _adapter(handler)
    provider = PandaScoreEsportsProvider(adapter, NoResolver())  # type: ignore[arg-type]

    async def exercise():
        try:
            return await provider.search(
                EsportsSearchRequest(kind="match", teams=["Alpha"], time_scope="upcoming")
            )
        finally:
            await adapter.aclose()

    batch = asyncio.run(exercise())
    assert [entity.source_identity for entity in batch.entities] == [72]


def test_team_identity_resolution_accepts_exact_acronym_and_slug_without_name_search() -> None:
    xg = {
        "id": 73,
        "name": "Xtreme Gaming",
        "acronym": "XG",
        "slug": "xtreme-gaming",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/dota2/teams":
            assert "search[name]" not in request.url.params
            return httpx.Response(200, json=[xg], headers={"X-Total": "1"})
        if request.url.path == "/teams/73/matches":
            return httpx.Response(
                200,
                json=[_match(74, name="XG match", teams=[xg])],
                headers={"X-Total": "1"},
            )
        raise AssertionError(request.url.path)

    adapter = _adapter(handler)
    provider = PandaScoreEsportsProvider(adapter, NoResolver())  # type: ignore[arg-type]

    async def exercise() -> list[int]:
        try:
            acronym = await provider.search(EsportsSearchRequest(kind="match", teams=["XG"]))
            slug = await provider.search(
                EsportsSearchRequest(kind="match", teams=["xtreme-gaming"])
            )
            return [acronym.entities[0].source_identity, slug.entities[0].source_identity]
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == [74, 74]


@pytest.mark.parametrize(
    ("team_payload", "expected_details"),
    [
        (
            [],
            {"argument": "teams", "team": "XG", "reason": "not_found"},
        ),
        (
            [_team(81, "XG"), _team(82, "XG")],
            {
                "argument": "teams",
                "team": "XG",
                "reason": "ambiguous",
                "candidate_count": 2,
            },
        ),
    ],
)
def test_team_identity_resolution_reports_not_found_or_ambiguous(
    team_payload: list[dict[str, object]],
    expected_details: dict[str, object],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/dota2/teams"
        return httpx.Response(200, json=team_payload, headers={"X-Total": str(len(team_payload))})

    adapter = _adapter(handler)
    provider = PandaScoreEsportsProvider(adapter, NoResolver())  # type: ignore[arg-type]

    async def exercise() -> None:
        try:
            await provider.search(EsportsSearchRequest(kind="match", teams=["XG"]))
        finally:
            await adapter.aclose()

    with pytest.raises(EsportsInvalidArgumentsError) as exc_info:
        asyncio.run(exercise())
    assert exc_info.value.details == expected_details


def test_unique_team_identities_without_a_common_match_return_no_records() -> None:
    alpha = _team(91, "Alpha")
    beta = _team(92, "Beta")
    gamma = _team(93, "Gamma")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/dota2/teams":
            assert "search[name]" not in request.url.params
            return httpx.Response(200, json=[alpha, beta], headers={"X-Total": "2"})
        if request.url.path == "/teams/91/matches":
            return httpx.Response(
                200,
                json=[_match(94, name="Alpha vs Gamma", teams=[alpha, gamma])],
                headers={"X-Total": "1"},
            )
        raise AssertionError(request.url.path)

    adapter = _adapter(handler)
    provider = PandaScoreEsportsProvider(adapter, NoResolver())  # type: ignore[arg-type]

    async def exercise():
        try:
            return await provider.search(
                EsportsSearchRequest(kind="match", teams=["Alpha", "Beta"])
            )
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()).entities == []


class UnavailableResolver:
    def __init__(
        self, error: OpenDotaTimeoutError | OpenDotaConfigurationError | OpenDotaSchemaError
    ):
        self._error = error

    async def resolve_many(self, match, games):  # type: ignore[no-untyped-def]
        raise self._error


@pytest.mark.parametrize(
    "error",
    [
        OpenDotaTimeoutError("timeout"),
        OpenDotaConfigurationError("configuration"),
        OpenDotaSchemaError("schema"),
    ],
)
def test_opendota_enrichment_failures_degrade_match_games(
    error: OpenDotaTimeoutError | OpenDotaConfigurationError | OpenDotaSchemaError,
) -> None:
    raw_match = _match(101, name="Degraded match")
    raw_match["games"] = [{"id": 102, "status": "finished", "provider_extra": "kept"}]

    class InlineAdapter:
        async def list_matches(self, **kwargs):  # type: ignore[no-untyped-def]
            from app.vnext.providers.common import ProviderBatch
            from app.vnext.providers.pandascore.models import PandaScoreMatch

            return ProviderBatch(
                [PandaScoreMatch.model_validate(raw_match)],
                datetime(2026, 8, 30, tzinfo=timezone.utc),
                has_more=False,
            )

    provider = PandaScoreEsportsProvider(InlineAdapter(), UnavailableResolver(error))  # type: ignore[arg-type]
    batch = asyncio.run(provider.search(EsportsSearchRequest(kind="match", time_scope="past")))

    game = batch.entities[0].document["games"][0]
    assert game["provider_extra"] == "kept"
    assert game["valve_game_id"] is None
    assert game["resolution"] == "unavailable"
