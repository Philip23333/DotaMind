"""Provider-level tests with inline PandaScore payloads and MockTransport."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from app.vnext.artifacts import ArtifactReader, MemoryArtifactStore
from app.vnext.capabilities.esports.models import EsportsSearchRequest
from app.vnext.capabilities.esports.pandascore import PandaScoreEsportsProvider
from app.vnext.capabilities.esports.service import EsportsSearchService
from app.vnext.domain.matches.resolution import ResolutionDecision
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
            query = request.url.params["search[name]"]
            return httpx.Response(
                200, json=[alpha if query == "Alpha" else beta], headers={"X-Total": "1"}
            )
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
