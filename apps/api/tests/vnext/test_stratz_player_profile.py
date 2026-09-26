from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.vnext.capabilities.player.profile import PlayerProfileInput, PlayerProfileResult
from app.vnext.composition import (
    VNextServices,
    VNextSettings,
    build_vnext_registry,
    build_vnext_services,
)
from app.vnext.llm.protocol import ToolCall
from app.vnext.providers.stratz.client import StratzGraphQLClient
from app.vnext.providers.stratz.player_profile import (
    PLAYER_PROFILE_QUERY,
    StratzPlayerProfileAdapter,
)
from app.vnext.tools.errors import StructuredToolError
from app.vnext.tools.player.profile import PLAYER_PROFILE_DESCRIPTION

_ACCOUNT_ID = 123456789
_TOKEN = "test-stratz-token-never-log"
_SENSITIVE = "sensitive-provider-body-do-not-expose"


def _run(awaitable):
    return asyncio.run(asyncio.wait_for(awaitable, timeout=2))


def _profile(**updates: Any) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "steamAccountId": _ACCOUNT_ID,
        "matchCount": 0,
        "winCount": 0,
        "imp": 0,
        "firstMatchDate": None,
        "lastMatchDate": 0,
        "steamAccount": {
            "id": 76561198000000000,
            "name": None,
            "avatar": "https://example.test/avatar.png",
            "seasonRank": 0,
            "smurfFlag": 0,
            "proSteamAccount": {"name": "Example Pro"},
            "providerExtension": {"nested": [None, False, 0]},
        },
        "providerExtension": {"nested": [None, True, 0], "flag": False},
    }
    profile.update(updates)
    return profile


def _response(profile: dict[str, Any] | None) -> dict[str, Any]:
    return {"data": {"player": profile}}


def _adapter(handler, *, transport: httpx.AsyncBaseTransport | None = None):
    if transport is None:
        transport = httpx.MockTransport(handler)
    client = StratzGraphQLClient(
        graphql_url="https://api.stratz.test/graphql",
        token=_TOKEN,
        timeout_seconds=3,
        transport=transport,
    )
    return StratzPlayerProfileAdapter(client)


def test_profile_query_uses_fixed_graphql_operation_variables_and_bearer_auth() -> None:
    observed: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["url"] = str(request.url)
        observed["headers"] = dict(request.headers)
        observed["body"] = json.loads(request.content)
        return httpx.Response(200, json=_response(_profile()), request=request)

    adapter = _adapter(handler)
    result = _run(adapter.get_profile(PlayerProfileInput(steam_account_id=_ACCOUNT_ID)))

    assert observed["method"] == "POST"
    assert observed["url"] == "https://api.stratz.test/graphql"
    assert observed["headers"]["authorization"] == f"Bearer {_TOKEN}"
    assert observed["headers"]["accept"] == "application/json"
    assert observed["headers"]["user-agent"] == "STRATZ_API"
    assert observed["body"]["variables"] == {"steamAccountId": _ACCOUNT_ID}
    assert observed["body"]["query"] == PLAYER_PROFILE_QUERY
    assert "player(steamAccountId: $steamAccountId)" in PLAYER_PROFILE_QUERY
    assert _TOKEN not in repr(result.model_dump(mode="json"))
    assert result.found is True
    assert result.profile == _profile()
    assert result.retrieved_at.tzinfo is not None
    assert adapter.client.timeout_seconds == 3


def test_null_player_is_not_found_and_optional_profile_fields_may_be_missing() -> None:
    null_adapter = _adapter(
        lambda request: httpx.Response(200, json=_response(None), request=request)
    )
    missing_optional_adapter = _adapter(
        lambda request: httpx.Response(
            200,
            json=_response({"steamAccountId": _ACCOUNT_ID}),
            request=request,
        )
    )

    missing = _run(null_adapter.get_profile(PlayerProfileInput(steam_account_id=_ACCOUNT_ID)))
    found = _run(
        missing_optional_adapter.get_profile(PlayerProfileInput(steam_account_id=_ACCOUNT_ID))
    )

    assert missing.model_dump(mode="json")["profile"] is None
    assert missing.found is False
    assert found.found is True
    assert found.profile == {"steamAccountId": _ACCOUNT_ID}


def test_profile_preserves_null_zero_boolean_and_unknown_nested_fields() -> None:
    adapter = _adapter(
        lambda request: httpx.Response(200, json=_response(_profile()), request=request)
    )

    result = _run(adapter.get_profile(PlayerProfileInput(steam_account_id=_ACCOUNT_ID)))

    assert result.profile is not None
    assert result.profile["matchCount"] == 0
    assert result.profile["firstMatchDate"] is None
    assert result.profile["providerExtension"] == {"nested": [None, True, 0], "flag": False}
    assert result.profile["steamAccount"]["providerExtension"] == {
        "nested": [None, False, 0]
    }


@pytest.mark.parametrize(
    ("payload", "expected_path"),
    [
        ({}, "data"),
        ({"data": None}, "data"),
        ({"data": {}}, "data.player"),
        ({"data": {"player": {}}}, "data.player"),
        ({"data": {"player": []}}, "data.player"),
        ({"data": {"player": {"steamAccountId": True}}}, "data.player.steamAccountId"),
        ({"data": {"player": {"steamAccountId": "123"}}}, "data.player.steamAccountId"),
        ({"data": {"player": {"steamAccountId": 12}}}, "data.player.steamAccountId"),
        (
            {"data": {"player": {"steamAccountId": _ACCOUNT_ID, "matchCount": "0"}}},
            "data.player.matchCount",
        ),
        (
            {"data": {"player": {"steamAccountId": _ACCOUNT_ID, "steamAccount": []}}},
            "data.player.steamAccount",
        ),
        (
            {
                "data": {
                    "player": {
                        "steamAccountId": _ACCOUNT_ID,
                        "steamAccount": {"seasonRank": "1"},
                    }
                }
            },
            "data.player.steamAccount.seasonRank",
        ),
        (
            {
                "data": {
                    "player": {
                        "steamAccountId": _ACCOUNT_ID,
                        "steamAccount": {"id": True},
                    }
                }
            },
            "data.player.steamAccount.id",
        ),
    ],
)
def test_malformed_player_shapes_return_provider_schema_error(
    payload: dict[str, Any], expected_path: str
) -> None:
    adapter = _adapter(lambda request: httpx.Response(200, json=payload, request=request))

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_profile(PlayerProfileInput(steam_account_id=_ACCOUNT_ID)))

    assert raised.value.code == "provider_schema_error"
    assert raised.value.details["path"] == expected_path
    assert _TOKEN not in str(raised.value)


def test_graphql_errors_fail_even_when_partial_player_data_is_present() -> None:
    adapter = _adapter(
        lambda request: httpx.Response(
            200,
            json={"data": {"player": _profile()}, "errors": [{"message": _SENSITIVE}]},
            request=request,
        )
    )

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_profile(PlayerProfileInput(steam_account_id=_ACCOUNT_ID)))

    assert raised.value.code == "provider_error"
    assert _SENSITIVE not in str(raised.value)
    assert _TOKEN not in str(raised.value)


@pytest.mark.parametrize("status_code", [401, 429, 500])
def test_http_auth_rate_limit_and_server_errors_are_structured_and_sanitized(
    status_code: int,
) -> None:
    adapter = _adapter(
        lambda request: httpx.Response(
            status_code,
            text=f"{_SENSITIVE} {_TOKEN}",
            request=request,
        )
    )

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_profile(PlayerProfileInput(steam_account_id=_ACCOUNT_ID)))

    assert raised.value.code == "provider_http_error"
    assert raised.value.details == {"provider": "stratz", "status_code": status_code}
    assert _SENSITIVE not in str(raised.value)
    assert _TOKEN not in str(raised.value)


@pytest.mark.parametrize("body", ["not-json", "[]", "{broken"])
def test_invalid_graphql_response_is_a_sanitized_schema_error(body: str) -> None:
    adapter = _adapter(lambda request: httpx.Response(200, text=body, request=request))

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_profile(PlayerProfileInput(steam_account_id=_ACCOUNT_ID)))

    assert raised.value.code == "provider_schema_error"
    assert _SENSITIVE not in str(raised.value)
    assert _TOKEN not in str(raised.value)


def test_request_timeout_maps_to_provider_timeout_without_echoing_transport_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"{_SENSITIVE} {_TOKEN}", request=request)

    adapter = _adapter(handler)

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_profile(PlayerProfileInput(steam_account_id=_ACCOUNT_ID)))

    assert raised.value.code == "provider_timeout"
    assert _SENSITIVE not in str(raised.value)
    assert _TOKEN not in str(raised.value)


class _ClosingTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler) -> None:
        self.handler = handler
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.handler(request)

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize("mode", ["success", "error", "cancel"])
def test_http_transport_closes_after_success_failure_and_cancellation(mode: str) -> None:
    async def scenario() -> None:
        started = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            if mode == "cancel":
                started.set()
                await asyncio.Event().wait()
            if mode == "error":
                return httpx.Response(401, request=request)
            return httpx.Response(200, json=_response(_profile()), request=request)

        transport = _ClosingTransport(handler)
        adapter = _adapter(None, transport=transport)
        operation = adapter.get_profile(PlayerProfileInput(steam_account_id=_ACCOUNT_ID))
        if mode == "cancel":
            task = asyncio.create_task(operation)
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)
        elif mode == "error":
            with pytest.raises(StructuredToolError):
                await operation
        else:
            await operation
        assert transport.closed is True

    _run(scenario())


def test_profile_tool_schema_registration_and_contract() -> None:
    registry = build_vnext_registry(
        services=VNextServices(
            player_profile=lambda query: _profile_result(query.steam_account_id)
        ),
        settings=VNextSettings(),
    )
    definition = registry.get("player.profile")
    schema = next(schema for schema in registry.schemas() if schema.name == "player.profile")

    assert definition.input_model is PlayerProfileInput
    assert definition.output_model is PlayerProfileResult
    assert definition.read_only is True
    assert schema.input_schema["properties"]["steam_account_id"]["minimum"] == 1
    assert schema.input_schema["properties"]["steam_account_id"]["maximum"] == 2**32 - 1
    assert "SteamID64" in PLAYER_PROFILE_DESCRIPTION
    assert "does not prove" in PLAYER_PROFILE_DESCRIPTION
    assert "player.recent_games" not in {tool.name for tool in registry.schemas()}
    assert "game.detail" not in {tool.name for tool in registry.schemas()}


def _profile_result(account_id: int) -> PlayerProfileResult:
    return PlayerProfileResult(
        steam_account_id=account_id,
        provider="stratz",
        retrieved_at=datetime.now(UTC),
        found=True,
        profile={"steamAccountId": account_id},
    )


def test_stratz_tool_is_registered_only_when_token_is_configured_and_build_is_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original_graphql = StratzGraphQLClient.graphql

    async def counted_graphql(self, query, variables):
        nonlocal calls
        calls += 1
        return await original_graphql(self, query, variables)

    monkeypatch.setattr(StratzGraphQLClient, "graphql", counted_graphql)
    no_token = VNextSettings(stratz_token="")
    token_configured = VNextSettings(stratz_token=_TOKEN)

    absent_registry = build_vnext_registry(settings=no_token)
    configured_services = build_vnext_services(token_configured)
    configured_registry = build_vnext_registry(configured_services, settings=token_configured)

    assert "player.profile" not in {tool.name for tool in absent_registry.schemas()}
    assert "player.profile" in {tool.name for tool in configured_registry.schemas()}
    assert calls == 0


def test_large_player_profile_result_uses_existing_artifact_externalization() -> None:
    async def lookup(query: PlayerProfileInput) -> PlayerProfileResult:
        return PlayerProfileResult(
            steam_account_id=query.steam_account_id,
            provider="stratz",
            retrieved_at=datetime.now(UTC),
            found=True,
            profile={"steamAccountId": query.steam_account_id, "extended": "x" * 16000},
        )

    registry = build_vnext_registry(
        services=VNextServices(player_profile=lookup), settings=VNextSettings()
    )
    result = _run(
        registry.execute(
            ToolCall(
                id="profile-call",
                name="player.profile",
                arguments={"steam_account_id": _ACCOUNT_ID},
            )
        )
    )

    assert result.status == "ok"
    assert result.content["externalized"] is True
    assert result.content["artifact_ref"].startswith("artifact:tool:")


def test_profile_tool_executes_through_registry_and_returns_validated_output() -> None:
    async def lookup(query: PlayerProfileInput) -> PlayerProfileResult:
        return _profile_result(query.steam_account_id)

    registry = build_vnext_registry(
        services=VNextServices(player_profile=lookup), settings=VNextSettings()
    )

    result = _run(
        registry.execute(
            ToolCall(
                id="profile-call",
                name="player.profile",
                arguments={"steam_account_id": _ACCOUNT_ID},
            )
        )
    )

    assert result.status == "ok"
    assert result.content["provider"] == "stratz"
    assert result.content["steam_account_id"] == _ACCOUNT_ID


def test_structured_provider_failure_reaches_registry_without_sensitive_text() -> None:
    adapter = _adapter(
        lambda request: httpx.Response(429, text=f"{_TOKEN} {_SENSITIVE}", request=request)
    )
    registry = build_vnext_registry(
        services=VNextServices(player_profile=adapter.get_profile),
        settings=VNextSettings(),
    )

    result = _run(
        registry.execute(
            ToolCall(
                id="profile-call",
                name="player.profile",
                arguments={"steam_account_id": _ACCOUNT_ID},
            )
        )
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "provider_http_error"
    assert result.error.details == {"provider": "stratz", "status_code": 429}
    serialized = json.dumps(result.model_dump(mode="json"))
    assert _TOKEN not in serialized
    assert _SENSITIVE not in serialized
