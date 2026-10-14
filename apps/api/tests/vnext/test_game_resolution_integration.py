from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from functools import wraps
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.vnext.capabilities.esports.game_resolution import GameResolutionService
from app.vnext.providers.match_resolution import (
    GameResolutionReadPolicy,
    PandaScoreOpenDotaGameResolutionProvider,
)
from app.vnext.providers.opendota.client import OpenDotaClient
from app.vnext.providers.opendota.discovery import OpenDotaDiscoveryAdapter
from app.vnext.providers.opendota.game_detail import OpenDotaGameDetailAdapter
from app.vnext.providers.pandascore.client import PandaScoreClient
from app.vnext.providers.pandascore.match_context import (
    PandaScoreMatchContextAdapter,
)
from app.vnext.tools.errors import StructuredToolError

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "game_resolution"
_MATCH_ID = 1_743_565
_PANDASCORE_GAME_ID = 740_250
_GAME_POSITION = 1
_LEAGUE_ID = 19_944
_VALVE_GAME_ID = 9_042_720_328
_FIXTURE_NAMES = (
    "pandascore_match_1743565.json",
    "opendota_leagues.json",
    "opendota_league_19944_matches.json",
    "opendota_game_9042720328.json",
)
_MATCH_OVERRIDE = object()


def _async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def _read_fixture(name: str) -> Any:
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _policy(*, max_requests: int = 6) -> GameResolutionReadPolicy:
    return GameResolutionReadPolicy(
        start_time_tolerance_seconds=1800,
        duration_tolerance_seconds=5,
        max_leagues=2,
        max_candidate_details=2,
        max_requests=max_requests,
    )


def _service(
    *,
    failure: tuple[str, str] | None = None,
    match_response: Any = _MATCH_OVERRIDE,
    max_requests: int = 6,
):
    match = _read_fixture("pandascore_match_1743565.json")
    leagues = _read_fixture("opendota_leagues.json")
    league_matches = _read_fixture("opendota_league_19944_matches.json")
    game_detail = _read_fixture("opendota_game_9042720328.json")
    if match_response is _MATCH_OVERRIDE:
        match_rows = [deepcopy(match)]
    else:
        match_rows = deepcopy(match_response)

    requests: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method != "GET":
            raise AssertionError(f"unexpected method: {request.method}")

        if request.url.host == "pandascore.test":
            if request.url.path != "/dota2/matches":
                raise AssertionError(f"unexpected PandaScore path: {request.url.path}")
            if dict(request.url.params) != {
                "filter[id]": str(_MATCH_ID),
                "page": "1",
                "per_page": "2",
            }:
                raise AssertionError(f"unexpected PandaScore query: {request.url.params}")
            if request.headers.get("authorization") != "Bearer integration-test-token":
                raise AssertionError("PandaScore client did not use the test token")
            return httpx.Response(200, json=match_rows, request=request)

        if request.url.host != "opendota.test":
            raise AssertionError(f"unexpected host: {request.url.host}")
        if request.url.query:
            raise AssertionError("unexpected OpenDota query parameters")

        if request.url.path == "/api/leagues":
            if failure == ("leagues", "429"):
                return httpx.Response(429, json={"error": "synthetic rate limit"}, request=request)
            return httpx.Response(200, json=leagues, request=request)
        if request.url.path == f"/api/leagues/{_LEAGUE_ID}/matches":
            if failure == ("league_matches", "shape"):
                return httpx.Response(200, json={"unexpected": "object"}, request=request)
            if failure == ("league_matches", "429"):
                return httpx.Response(429, json={"error": "synthetic rate limit"}, request=request)
            return httpx.Response(200, json=league_matches, request=request)
        if request.url.path == f"/api/matches/{_VALVE_GAME_ID}":
            if failure == ("game_detail", "429"):
                return httpx.Response(429, json={"error": "synthetic rate limit"}, request=request)
            if failure == ("game_detail", "timeout"):
                raise httpx.ReadTimeout("synthetic timeout", request=request)
            payload = deepcopy(game_detail)
            if failure == ("game_detail", "wrong_identity"):
                payload["match_id"] = _VALVE_GAME_ID - 1
            return httpx.Response(200, json=payload, request=request)
        raise AssertionError(f"unexpected OpenDota path: {request.url.path}")

    mock_transport = httpx.MockTransport(transport)
    pandascore = PandaScoreMatchContextAdapter(
        PandaScoreClient(
            base_url="https://pandascore.test",
            token="integration-test-token",
            timeout_seconds=5,
            transport=mock_transport,
        )
    )
    opendota_client = OpenDotaClient(
        base_url="https://opendota.test/api",
        timeout_seconds=5,
        transport=mock_transport,
    )
    provider = PandaScoreOpenDotaGameResolutionProvider(
        pandascore,
        OpenDotaDiscoveryAdapter(opendota_client),
        OpenDotaGameDetailAdapter(opendota_client),
    )
    service = GameResolutionService(provider, policy=_policy(max_requests=max_requests))
    return service, requests


@pytest.fixture(autouse=True)
def _fixtures_are_not_modified():
    before = {
        name: hashlib.sha256((_FIXTURE_DIR / name).read_bytes()).hexdigest()
        for name in (*_FIXTURE_NAMES, "manifest.json")
    }
    yield
    after = {
        name: hashlib.sha256((_FIXTURE_DIR / name).read_bytes()).hexdigest()
        for name in (*_FIXTURE_NAMES, "manifest.json")
    }
    assert after == before


@_async_test
async def test_historical_responses_resolve_through_real_clients_adapters_and_service() -> None:
    service, requests = _service()

    result = await service.resolve(
        _MATCH_ID,
        _GAME_POSITION,
        confirmed_mappings={},
    )

    assert result.status == "resolved"
    assert result.valve_game_id == _VALVE_GAME_ID
    assert result.game_position == _GAME_POSITION
    assert result.method == "inferred_cross_source"
    assert result.providers == ["pandascore", "opendota"]
    assert result.data["requests_started"] == 4
    assert len(requests) == 4
    assert [(request.url.host, request.url.path) for request in requests] == [
        ("pandascore.test", "/dota2/matches"),
        ("opendota.test", "/api/leagues"),
        ("opendota.test", f"/api/leagues/{_LEAGUE_ID}/matches"),
        ("opendota.test", f"/api/matches/{_VALVE_GAME_ID}"),
    ]
    assert dict(requests[0].url.params) == {
        "filter[id]": str(_MATCH_ID),
        "page": "1",
        "per_page": "2",
    }
    assert all(not request.url.params for request in requests[1:])

    match = _read_fixture("pandascore_match_1743565.json")
    assert match["status"] == "running"
    target_game = next(game for game in match["games"] if game["position"] == 1)
    assert target_game["id"] == _PANDASCORE_GAME_ID
    assert target_game["begin_at"] == "2026-10-13T07:05:15Z"
    assert target_game["length"] == 2090
    assert result.data["target_game_result"]["target_game"] == target_game
    assert not {
        "pandascore_match_context", "opendota_leagues",
        "league_matches_by_id", "candidate_details",
    } & result.data.keys()

    resolution = result.data["resolution_result"]
    assert resolution["searched_league_ids"] == [_LEAGUE_ID]
    assert resolution["pandascore_match_id"] == _MATCH_ID
    assert resolution["pandascore_game_id"] == _PANDASCORE_GAME_ID
    assert resolution["valve_game_id"] == _VALVE_GAME_ID
    assert len(resolution["candidate_assessments"]) == 1
    evidence = resolution["candidate_assessments"][0]["league_assessments"][0][
        "assessment"
    ]
    assert evidence["candidate_valve_game_id"] == _VALVE_GAME_ID
    assert evidence["detail_start_delta_seconds"] == -157.0
    assert evidence["detail_duration_delta_seconds"] == 0
    assert evidence["status"] == "accepted"
    assert evidence["identity_evidence"]["participants_status"] == "supported"
    assert evidence["identity_evidence"]["winner_status"] == "consistent"


@_async_test
async def test_request_budget_of_three_stops_before_detail_request() -> None:
    service, requests = _service(max_requests=3)

    with pytest.raises(StructuredToolError) as raised:
        await service.resolve(_MATCH_ID, _GAME_POSITION, confirmed_mappings={})

    error = raised.value
    assert error.code == "tool_execution_error"
    assert error.details["category"] == "budget_exhausted"
    assert error.details["operation"] == "candidate_details"
    assert error.details["requests_started"] == 3
    assert error.details["required"] == 1
    assert len(requests) == 3
    assert requests[-1].url.path == f"/api/leagues/{_LEAGUE_ID}/matches"


@_async_test
async def test_empty_match_response_stops_before_opendota() -> None:
    service, requests = _service(match_response=[])

    result = await service.resolve(_MATCH_ID, _GAME_POSITION, confirmed_mappings={})

    assert result.status == "unresolved"
    assert result.reason == "match_not_found"
    assert result.providers == ["pandascore"]
    assert result.data["stage"] == "match_context"
    assert result.data["target_game_result"] is None
    assert result.data["league_candidate_result"] is None
    assert result.data["resolution_result"] is None
    assert len(requests) == 1
    assert requests[0].url.host == "pandascore.test"


@_async_test
async def test_non_list_league_matches_response_is_rejected_by_real_adapter() -> None:
    service, requests = _service(failure=("league_matches", "shape"))

    with pytest.raises(StructuredToolError) as raised:
        await service.resolve(_MATCH_ID, _GAME_POSITION, confirmed_mappings={})

    error = raised.value
    assert error.code == "provider_schema_error"
    assert error.details["provider"] == "opendota"
    assert error.details["path"] == "response"
    assert error.details["operation"] == "league_matches"
    assert error.details["requests_started"] == 3
    assert len(requests) == 3


@_async_test
async def test_wrong_detail_identity_is_rejected_by_real_adapter() -> None:
    service, requests = _service(failure=("game_detail", "wrong_identity"))

    with pytest.raises(StructuredToolError) as raised:
        await service.resolve(_MATCH_ID, _GAME_POSITION, confirmed_mappings={})

    error = raised.value
    assert error.code == "provider_schema_error"
    assert error.details["provider"] == "opendota"
    assert error.details["path"] == "match_id"
    assert error.details["operation"] == "game_detail"
    assert error.details["requests_started"] == 4
    assert len(requests) == 4


@_async_test
async def test_http_429_preserves_provider_status_stage_and_request_count() -> None:
    service, requests = _service(failure=("game_detail", "429"))

    with pytest.raises(StructuredToolError) as raised:
        await service.resolve(_MATCH_ID, _GAME_POSITION, confirmed_mappings={})

    error = raised.value
    assert error.code == "provider_http_error"
    assert error.details["status_code"] == 429
    assert error.details["operation"] == "game_detail"
    assert error.details["requests_started"] == 4
    assert len(requests) == 4


@_async_test
async def test_detail_timeout_is_not_retried_and_keeps_stable_error() -> None:
    service, requests = _service(failure=("game_detail", "timeout"))

    with pytest.raises(StructuredToolError) as raised:
        await service.resolve(_MATCH_ID, _GAME_POSITION, confirmed_mappings={})

    error = raised.value
    assert error.code == "provider_timeout"
    assert error.details["provider"] == "opendota"
    assert error.details["operation"] == "game_detail"
    assert error.details["requests_started"] == 4
    assert len(requests) == 4


def test_fixture_manifest_hashes_capture_time_and_historical_provenance() -> None:
    manifest = _read_fixture("manifest.json")

    assert manifest["schema_version"] == 1
    assert manifest["source"]["observed_at"] == "2026-10-13T16:34:21.665870+08:00"
    assert manifest["source"]["historical_only"] is True
    assert manifest["baseline"]["parent_match_status"] == "running"
    assert manifest["baseline"]["start_delta_seconds"] == -157
    assert manifest["baseline"]["duration_delta_seconds"] == 0
    assert manifest["counts"] == {
        "opendota_leagues": 10_352,
        "opendota_league_matches": 353,
    }
    for name in _FIXTURE_NAMES:
        actual = hashlib.sha256((_FIXTURE_DIR / name).read_bytes()).hexdigest()
        assert actual == manifest["fixtures"][name]["sha256"]
