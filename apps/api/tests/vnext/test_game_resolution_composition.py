from __future__ import annotations

import asyncio
import json
from functools import wraps
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.vnext import composition
from app.vnext.composition import VNextSettings, build_vnext_registry, build_vnext_services
from app.vnext.llm.protocol import ToolCall
from app.vnext.providers.match_resolution import GameResolutionReadPolicy
from app.vnext.providers.opendota.client import OpenDotaClient as RealOpenDotaClient
from app.vnext.providers.pandascore.client import PandaScoreClient as RealPandaScoreClient

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "game_resolution"
_MATCH_ID = 1_743_565
_LEAGUE_ID = 19_944
_VALVE_GAME_ID = 9_042_720_328


def _async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def _fixture(name: str) -> Any:
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _policy(*, max_requests: int = 16) -> GameResolutionReadPolicy:
    return GameResolutionReadPolicy(
        start_time_tolerance_seconds=1800,
        duration_tolerance_seconds=5,
        max_leagues=6,
        max_candidate_details=8,
        max_requests=max_requests,
    )


def _call(name: str, arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(id=f"call-{name}", name=name, arguments=arguments)


def _product_stack(
    monkeypatch: pytest.MonkeyPatch,
    *,
    policy: GameResolutionReadPolicy | None = None,
    fault: str | None = None,
    match_context_entered: asyncio.Event | None = None,
    release_match_context: asyncio.Event | None = None,
):
    match = _fixture("pandascore_match_1743565.json")
    leagues = _fixture("opendota_leagues.json")
    league_matches = _fixture("opendota_league_19944_matches.json")
    game_detail = _fixture("opendota_game_9042720328.json")
    requests: list[httpx.Request] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        if request.url.host == "pandascore.test":
            assert request.url.path == "/dota2/matches"
            assert request.headers.get("authorization") == "Bearer composition-test-token"
            params = dict(request.url.params)
            assert params.get("filter[id]") == str(_MATCH_ID)
            if params.get("per_page") == "20":
                assert params == {
                    "filter[id]": str(_MATCH_ID),
                    "page": "1",
                    "per_page": "20",
                }
            else:
                assert params == {
                    "filter[id]": str(_MATCH_ID),
                    "page": "1",
                    "per_page": "2",
                }
                if match_context_entered is not None:
                    match_context_entered.set()
                    assert release_match_context is not None
                    await release_match_context.wait()
            return httpx.Response(200, json=[match], request=request)

        assert request.url.host == "opendota.test"
        assert "authorization" not in request.headers
        assert not request.url.query
        if request.url.path == "/api/leagues":
            if fault == "leagues_429":
                return httpx.Response(429, json={"error": "synthetic"}, request=request)
            return httpx.Response(200, json=leagues, request=request)
        if request.url.path == f"/api/leagues/{_LEAGUE_ID}/matches":
            rows = [] if fault == "empty_candidates" else league_matches
            return httpx.Response(200, json=rows, request=request)
        if request.url.path == f"/api/matches/{_VALVE_GAME_ID}":
            return httpx.Response(200, json=game_detail, request=request)
        raise AssertionError(f"unexpected HTTP route: {request.url}")

    transport = httpx.MockTransport(handle)
    def make_pandascore_client(**kwargs):
        return RealPandaScoreClient(**kwargs, transport=transport)

    def make_opendota_client(**kwargs):
        return RealOpenDotaClient(**kwargs, transport=transport)

    monkeypatch.setattr(composition, "PandaScoreClient", make_pandascore_client)
    monkeypatch.setattr(composition, "OpenDotaClient", make_opendota_client)
    settings = VNextSettings(
        pandascore_base_url="https://pandascore.test",
        pandascore_token="composition-test-token",
        opendota_enabled=True,
        opendota_base_url="https://opendota.test/api",
        game_resolution_enabled=True,
        game_resolution_read_policy=policy or _policy(),
    )
    services = build_vnext_services(settings)
    assert services.game_resolution is not None
    assert services.game_detail is not None
    assert services.game_resolution._policy is settings.game_resolution_read_policy
    resolution_provider = services.game_resolution._provider
    assert services.match_search is not None
    assert (
        services.match_search.__self__.client
        is resolution_provider._pandascore_match_context.client
    )
    assert (
        resolution_provider._opendota_game_detail is services.game_detail.__self__
    )
    assert (
        resolution_provider._opendota_discovery.client
        is services.game_detail.__self__.client
    )
    registry = build_vnext_registry(services, settings=settings)
    return settings, services, registry, requests


async def _search_match(registry) -> str:
    result = await registry.execute(
        _call("esports.match.search", {"id": _MATCH_ID})
    )
    assert result.status == "ok"
    assert result.content["externalized"] is True
    assert result.content["value"]["items"][0]["id"] == _MATCH_ID
    return result.content["artifact_ref"]


@_async_test
async def test_product_composition_runs_search_resolve_and_detail_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, _services, registry, requests = _product_stack(monkeypatch)
    assert requests == []  # Composition constructs clients but performs no startup probe.

    match_ref = await _search_match(registry)
    resolved = await registry.execute(
        _call(
            "esports.game.resolve",
            {
                "match_artifact_ref": match_ref,
                "match_path": "items.0",
                "game_position": 1,
            },
        )
    )
    assert resolved.status == "ok"
    assert resolved.content["value"]["status"] == "resolved"
    assert resolved.content["value"]["game_position"] == 1
    assert resolved.content["value"]["valve_game_id"] == _VALVE_GAME_ID
    assert resolved.content["value"]["reason"] is None
    resolved_valve_game_id = resolved.content["value"]["valve_game_id"]

    detail = await registry.execute(
        _call("game.detail", {"valve_game_id": resolved_valve_game_id})
    )
    assert detail.status == "ok"
    assert detail.content["externalized"] is True
    assert detail.content["value"]["valve_game_id"] == _VALVE_GAME_ID

    store = registry._result_processor._externalizer._store
    match_document = await store.get(match_ref)
    assert match_document["items"][0]["id"] == _MATCH_ID
    resolution_document = await store.get(resolved.content["artifact_ref"])
    assert resolution_document["status"] == "resolved"
    assert resolution_document["valve_game_id"] == _VALVE_GAME_ID
    attempt_data = resolution_document["data"]
    assert not {
        "pandascore_match_context", "opendota_leagues",
        "league_matches_by_id", "candidate_details",
    } & attempt_data.keys()
    assert attempt_data["resolution_result"]["valve_game_id"] == _VALVE_GAME_ID
    assert attempt_data["requests_started"] == 4
    resolution_ref = resolved.content["artifact_ref"]
    evidence_read = await registry.execute(
        _call("artifact.read", {
            "ref": resolution_ref, "mode": "read", "path": "data.resolution_result",
        })
    )
    assert evidence_read.status == "ok"
    rejected_read = await registry.execute(
        _call("artifact.read", {
            "ref": resolution_ref, "mode": "read", "path": "data.candidate_details",
        })
    )
    assert rejected_read.status == "error"
    assert rejected_read.error is not None
    assert rejected_read.error.code == "artifact_path_not_found"
    detail_document = await store.get(detail.content["artifact_ref"])
    assert detail_document["data"] == _fixture("opendota_game_9042720328.json")
    assert detail_document["valve_game_id"] == _VALVE_GAME_ID
    assert await store.get_source_tool(match_ref) == "esports.match.search"
    assert await store.get_source_tool(resolved.content["artifact_ref"]) == "esports.game.resolve"
    assert await store.get_source_tool(detail.content["artifact_ref"]) == "game.detail"

    assert [(request.url.host, request.url.path) for request in requests] == [
        ("pandascore.test", "/dota2/matches"),
        ("pandascore.test", "/dota2/matches"),
        ("opendota.test", "/api/leagues"),
        ("opendota.test", f"/api/leagues/{_LEAGUE_ID}/matches"),
        ("opendota.test", f"/api/matches/{_VALVE_GAME_ID}"),
        ("opendota.test", f"/api/matches/{_VALVE_GAME_ID}"),
    ]
    assert [dict(request.url.params).get("per_page") for request in requests[:2]] == [
        "20",
        "2",
    ]
    assert settings.game_resolution_enabled is True


@_async_test
async def test_two_product_registries_keep_match_artifacts_session_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, _services, first_registry, requests = _product_stack(monkeypatch)
    second_registry = build_vnext_registry(
        _services,
        settings=settings,
    )
    match_ref = await _search_match(first_registry)

    rejected = await second_registry.execute(
        _call(
            "esports.game.resolve",
            {
                "match_artifact_ref": match_ref,
                "match_path": "items.0",
                "game_position": 1,
            },
        )
    )

    assert rejected.status == "error"
    assert rejected.error is not None and rejected.error.code == "artifact_not_found"
    assert len(requests) == 1


@_async_test
async def test_product_registry_keeps_unresolved_budget_and_provider_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, unresolved_registry, unresolved_requests = _product_stack(
        monkeypatch,
        fault="empty_candidates",
    )
    match_ref = await _search_match(unresolved_registry)
    unresolved = await unresolved_registry.execute(
        _call(
            "esports.game.resolve",
            {
                "match_artifact_ref": match_ref,
                "match_path": "items.0",
                "game_position": 1,
            },
        )
    )
    assert unresolved.status == "ok"
    assert unresolved.content["value"]["status"] == "unresolved"
    assert unresolved.content["value"]["valve_game_id"] is None
    assert len(unresolved_requests) == 4

    _, _, budget_registry, budget_requests = _product_stack(
        monkeypatch,
        policy=_policy(max_requests=3),
    )
    budget_match_ref = await _search_match(budget_registry)
    exhausted = await budget_registry.execute(
        _call(
            "esports.game.resolve",
            {
                "match_artifact_ref": budget_match_ref,
                "match_path": "items.0",
                "game_position": 1,
            },
        )
    )
    assert exhausted.status == "error"
    assert exhausted.error is not None
    assert exhausted.error.code == "tool_execution_error"
    assert exhausted.error.details["category"] == "budget_exhausted"
    assert exhausted.error.details["operation"] == "candidate_details"
    assert len(budget_requests) == 4
    assert budget_requests[-1].url.path == f"/api/leagues/{_LEAGUE_ID}/matches"

    _, _, provider_registry, provider_requests = _product_stack(
        monkeypatch,
        fault="leagues_429",
    )
    provider_match_ref = await _search_match(provider_registry)
    provider_error = await provider_registry.execute(
        _call(
            "esports.game.resolve",
            {
                "match_artifact_ref": provider_match_ref,
                "match_path": "items.0",
                "game_position": 1,
            },
        )
    )
    assert provider_error.status == "error"
    assert provider_error.error is not None
    assert provider_error.error.code == "provider_http_error"
    assert provider_error.error.details["operation"] == "leagues"
    assert provider_error.error.details["status_code"] == 429
    assert len(provider_requests) == 3


@_async_test
async def test_cancellation_stops_product_resolution_before_following_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    _, _, registry, requests = _product_stack(
        monkeypatch,
        match_context_entered=entered,
        release_match_context=release,
    )
    match_ref = await _search_match(registry)
    task = asyncio.create_task(
        registry.execute(
            _call(
                "esports.game.resolve",
                {
                    "match_artifact_ref": match_ref,
                    "match_path": "items.0",
                    "game_position": 1,
                },
            )
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)

    assert len(requests) == 2
    assert [(request.url.host, request.url.path) for request in requests] == [
        ("pandascore.test", "/dota2/matches"),
        ("pandascore.test", "/dota2/matches"),
    ]
