from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.vnext.capabilities.game.detail import GameDetailInput, GameDetailResult
from app.vnext.composition import (
    VNextServices,
    VNextSettings,
    build_vnext_registry,
    build_vnext_services,
)
from app.vnext.llm.protocol import ToolCall
from app.vnext.providers.opendota import OpenDotaClient, OpenDotaGameDetailAdapter
from app.vnext.providers.stratz import StratzGraphQLClient, StratzPlayerRecentGamesAdapter
from app.vnext.tools.errors import StructuredToolError
from app.vnext.tools.game.detail import GAME_DETAIL_DESCRIPTION

_MATCH_ID = 8960882635
_KEY = "test-opendota-secret"


def _run(awaitable):
    return asyncio.run(awaitable)


def _match(match_id: int = _MATCH_ID, **overrides: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "match_id": match_id,
        "start_time": 1_780_000_000,
        "duration": 2_700,
        "radiant_win": False,
        "players": [
            {
                "account_id": 123456789,
                "player_slot": 0,
                "hero_id": 1,
                "isRadiant": True,
                "win": 0,
                "kills": 0,
                "deaths": 4,
                "assists": 8,
                "personaname": None,
                "purchase_log": [{"time": 0, "key": "item_tango"}],
            }
        ],
    }
    result.update(overrides)
    return result


def _adapter(handler, *, key: str = "", base_url: str = "https://api.example/api"):
    transport = httpx.MockTransport(handler)
    client = OpenDotaClient(
        base_url=base_url,
        api_key=key,
        timeout_seconds=3.25,
        transport=transport,
    )
    return OpenDotaGameDetailAdapter(client), client


def test_client_uses_match_endpoint_api_key_and_configured_timeout() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_match(), request=request)

    adapter, client = _adapter(handler, key=_KEY, base_url="https://api.example/root/api/")
    result = _run(adapter.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))

    assert seen[0].url.path == f"/root/api/matches/{_MATCH_ID}"
    assert seen[0].url.params.get("api_key") == _KEY
    assert client.timeout_seconds == 3.25
    assert result.valve_game_id == _MATCH_ID
    assert result.provider == "opendota"
    assert result.data["match_id"] == _MATCH_ID
    assert _KEY not in repr(client)
    assert _KEY not in str(result)


def test_full_source_object_preserves_unknown_nested_fields_null_zero_and_false() -> None:
    source = _match(
        radiant_win=False,
        radiant_gold_adv=[0, -12],
        private_extension={"unknown": [{"value": None, "enabled": False}]},
        players=[
            {
                "account_id": None,
                "hero_id": 0,
                "isRadiant": False,
                "win": 0,
                "personaname": None,
                "extension": {"items": [0, None, False]},
            }
        ],
    )
    adapter, _ = _adapter(lambda request: httpx.Response(200, json=source, request=request))

    result = _run(adapter.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))

    assert result.data == source
    assert result.model_dump(mode="json")["data"] == source
    assert result.data["radiant_win"] is False
    assert result.data["players"][0]["win"] == 0


@pytest.mark.parametrize(
    "source",
    [
        {"match_id": _MATCH_ID},
        {"match_id": _MATCH_ID, "players": None, "radiant_win": None},
    ],
)
def test_missing_optional_players_and_explicit_nulls_are_preserved(source) -> None:
    adapter, _ = _adapter(lambda request: httpx.Response(200, json=source, request=request))

    result = _run(adapter.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))

    assert result.data == source


def test_non_json_finite_extension_value_is_rejected_as_source_schema_error() -> None:
    adapter, _ = _adapter(
        lambda request: httpx.Response(
            200,
            content=f'{{"match_id":{_MATCH_ID},"extension":NaN}}'.encode(),
            headers={"Content-Type": "application/json"},
            request=request,
        )
    )

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))

    assert raised.value.code == "provider_schema_error"
    assert raised.value.details["path"] == "response"


@pytest.mark.parametrize(
    ("payload", "path"),
    [
        ([], "response"),
        ({}, "response"),
        ({"duration": 100}, "match_id"),
        ({"match_id": None}, "match_id"),
        ({"match_id": True}, "match_id"),
        ({"match_id": _MATCH_ID + 1}, "match_id"),
        ({"match_id": _MATCH_ID, "start_time": "later"}, "start_time"),
        ({"match_id": _MATCH_ID, "start_time": 0}, "start_time"),
        ({"match_id": _MATCH_ID, "duration": False}, "duration"),
        ({"match_id": _MATCH_ID, "duration": -1}, "duration"),
        ({"match_id": _MATCH_ID, "radiant_win": 0}, "radiant_win"),
        ({"match_id": _MATCH_ID, "players": {}}, "players"),
        ({"match_id": _MATCH_ID, "players": [None]}, "players.0"),
        (
            {"match_id": _MATCH_ID, "players": [{"account_id": "123"}]},
            "players.0.account_id",
        ),
        (
            {"match_id": _MATCH_ID, "players": [{"isRadiant": 1}]},
            "players.0.isRadiant",
        ),
    ],
)
def test_malformed_or_mismatched_source_records_are_schema_errors(payload, path: str) -> None:
    adapter, _ = _adapter(lambda request: httpx.Response(200, json=payload, request=request))

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))

    assert raised.value.code == "provider_schema_error"
    assert raised.value.details["path"] == path


@pytest.mark.parametrize(
    "error",
    ["match is unavailable", {"code": "NOT_FOUND"}, f"private {_KEY}"],
)
def test_success_status_provider_error_object_is_not_a_match(error) -> None:
    adapter, _ = _adapter(
        lambda request: httpx.Response(
            200,
            json={"error": error},
            request=request,
        )
    )

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))

    assert raised.value.code == "provider_error"
    assert str(error) not in str(raised.value)
    assert _KEY not in str(raised.value)


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (404, "not_found_or_unavailable"),
        (401, "authentication_or_access"),
        (403, "authentication_or_access"),
        (429, "rate_limited"),
        (500, "upstream_error"),
        (422, "http_error"),
    ],
)
def test_http_errors_keep_only_structured_status(status: int, category: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, text=f"private body {_KEY}", request=request)

    adapter, _ = _adapter(handler, key=_KEY)

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))

    assert raised.value.code == "provider_http_error"
    assert raised.value.details == {
        "provider": "opendota",
        "status_code": status,
        "category": category,
    }
    assert _KEY not in str(raised.value)
    assert len(requests) == 1


def test_non_json_success_is_a_sanitized_schema_error() -> None:
    adapter, _ = _adapter(
        lambda request: httpx.Response(200, text=f"not-json {_KEY}", request=request),
        key=_KEY,
    )

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))

    assert raised.value.code == "provider_schema_error"
    assert raised.value.details == {"provider": "opendota", "path": "response"}
    assert _KEY not in str(raised.value)


def test_timeout_is_structured_and_transport_error_does_not_leak_url() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timeout at {request.url}", request=request)

    adapter, _ = _adapter(timeout_handler, key=_KEY)
    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))
    assert raised.value.code == "provider_timeout"
    assert _KEY not in str(raised.value)

    calls = 0

    def transport_error(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError(f"connect failed for {request.url}", request=request)

    adapter, _ = _adapter(transport_error, key=_KEY)
    with pytest.raises(StructuredToolError) as transport_raised:
        _run(adapter.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID)))
    assert transport_raised.value.code == "provider_error"
    assert calls == 1
    assert _KEY not in str(transport_raised.value)


@pytest.mark.parametrize(
    "base_url",
    [
        "file:///tmp/opendota",
        "https://user:password@api.example/api",
        "https://api.example/api?api_key=embedded-secret",
        "not-a-url-with-secret",
    ],
)
def test_base_url_rejects_credentials_and_query_parameters(base_url: str) -> None:
    with pytest.raises(ValueError, match="base URL") as raised:
        OpenDotaClient(base_url=base_url)
    assert "secret" not in str(raised.value)


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf")])
def test_client_timeout_must_be_finite_positive(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout"):
        OpenDotaClient(timeout_seconds=timeout)


def test_cancel_propagates_and_closes_transport() -> None:
    class BlockingTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.exited = asyncio.Event()
            self.closed = False

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.exited.set()

        async def aclose(self) -> None:
            self.closed = True

    async def scenario() -> None:
        transport = BlockingTransport()
        adapter = OpenDotaGameDetailAdapter(OpenDotaClient(transport=transport, api_key=_KEY))
        task = asyncio.create_task(
            adapter.get_game_detail(GameDetailInput(valve_game_id=_MATCH_ID))
        )
        await asyncio.wait_for(transport.started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert transport.exited.is_set()
        assert transport.closed

    _run(asyncio.wait_for(scenario(), timeout=2))


def test_registry_gate_services_composition_and_no_network_on_build(monkeypatch) -> None:
    calls = 0

    async def forbidden_call(self, match_id):
        nonlocal calls
        calls += 1
        raise AssertionError("composition must not call the provider")

    monkeypatch.setattr(OpenDotaClient, "get_match", forbidden_call)
    disabled = build_vnext_registry(settings=VNextSettings())
    assert "game.detail" not in {tool.name for tool in disabled.schemas()}

    settings = VNextSettings(opendota_enabled=True)
    services = build_vnext_services(settings)
    enabled = build_vnext_registry(services, settings=settings)
    assert "game.detail" in {tool.name for tool in enabled.schemas()}
    definition = enabled.get("game.detail")
    assert definition.input_model is GameDetailInput
    assert definition.output_model is GameDetailResult
    assert definition.read_only is True
    assert "Valve" in GAME_DETAIL_DESCRIPTION
    assert "PandaScore" in GAME_DETAIL_DESCRIPTION
    assert "does not request replay parsing" in GAME_DETAIL_DESCRIPTION
    assert calls == 0

    injected = build_vnext_registry(
        VNextServices(game_detail=services.game_detail),
        settings=VNextSettings(opendota_enabled=False),
    )
    assert "game.detail" not in {tool.name for tool in injected.schemas()}


def test_game_detail_result_spills_to_artifact_and_reads_narrow_player_path() -> None:
    source = _match(extension="x" * 16_000)
    adapter, _ = _adapter(lambda request: httpx.Response(200, json=source, request=request))
    settings = VNextSettings(opendota_enabled=True)
    registry = build_vnext_registry(
        VNextServices(game_detail=adapter.get_game_detail),
        settings=settings,
    )

    result = _run(
        registry.execute(
            ToolCall(
                id="detail",
                name="game.detail",
                arguments={"valve_game_id": _MATCH_ID},
            )
        )
    )
    assert result.status == "ok"
    assert result.content["externalized"] is True
    ref = result.content["artifact_ref"]
    player_read = _run(
        registry.execute(
            ToolCall(
                id="player-read",
                name="artifact.read",
                arguments={
                    "ref": ref,
                    "mode": "read",
                    "path": "data.players.0.hero_id",
                },
            )
        )
    )
    assert player_read.status == "ok"
    assert player_read.content["value"] == 1


def test_recent_games_tool_id_flows_into_game_detail_tool() -> None:
    account_id = 123456789
    recent_match = {
        "id": _MATCH_ID,
        "startDateTime": 1_780_000_000,
        "durationSeconds": 2_700,
        "lobbyType": "RANKED",
        "gameMode": "ALL_PICK",
        "players": [
            {
                "steamAccountId": account_id,
                "heroId": 1,
                "isVictory": False,
                "isRadiant": True,
                "kills": 0,
                "deaths": 4,
                "assists": 8,
                "goldPerMinute": 400,
                "experiencePerMinute": 500,
                "position": None,
                "lane": None,
                "role": None,
                "imp": None,
                "level": 20,
                "numLastHits": 200,
                "numDenies": 5,
            }
        ],
    }
    stratz = StratzPlayerRecentGamesAdapter(
        StratzGraphQLClient(
            graphql_url="https://stratz.example/graphql",
            token="fixture-token",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "data": {
                            "player": {
                                "steamAccountId": account_id,
                                "matches": [recent_match],
                            }
                        }
                    },
                    request=request,
                )
            ),
        )
    )
    opendota, _ = _adapter(
        lambda request: httpx.Response(
            200,
            json=_match(
                radiant_win=False,
                players=[
                    {
                        "account_id": account_id,
                        "player_slot": 0,
                        "hero_id": 1,
                        "isRadiant": True,
                        "win": 0,
                    }
                ],
            ),
            request=request,
        )
    )
    registry = build_vnext_registry(
        VNextServices(
            player_recent_games=stratz.get_recent_games,
            game_detail=opendota.get_game_detail,
        ),
        settings=VNextSettings(opendota_enabled=True),
    )

    recent_result = _run(
        registry.execute(
            ToolCall(
                id="recent",
                name="player.recent_games",
                arguments={"steam_account_id": account_id},
            )
        )
    )
    assert recent_result.status == "ok"
    valve_id = recent_result.content["games"][0]["valve_game_id"]
    detail_result = _run(
        registry.execute(
            ToolCall(
                id="detail",
                name="game.detail",
                arguments={"valve_game_id": valve_id},
            )
        )
    )

    assert detail_result.status == "ok"
    detail = detail_result.content
    assert detail["valve_game_id"] == _MATCH_ID
    assert detail["data"]["match_id"] == _MATCH_ID
    assert detail["data"]["players"][0]["account_id"] == account_id
    assert detail["data"]["players"][0]["hero_id"] == recent_match["players"][0]["heroId"]
    assert detail["data"]["players"][0]["win"] == 0
    assert recent_match["players"][0]["isVictory"] is False
