from __future__ import annotations

import asyncio
import json
from datetime import UTC
from typing import Any

import httpx
import pytest

from app.vnext.capabilities.game import GameDetailInput
from app.vnext.capabilities.player import (
    PlayerRecentGamesInput,
    PlayerRecentGamesResult,
)
from app.vnext.composition import (
    VNextServices,
    VNextSettings,
    build_vnext_registry,
    build_vnext_services,
)
from app.vnext.llm.protocol import ToolCall
from app.vnext.providers.stratz.client import StratzGraphQLClient
from app.vnext.providers.stratz.player_recent_games import (
    PLAYER_RECENT_GAMES_QUERY,
    StratzPlayerRecentGamesAdapter,
)
from app.vnext.tools.errors import StructuredToolError
from app.vnext.tools.player.recent_games import PLAYER_RECENT_GAMES_DESCRIPTION

_ACCOUNT_ID = 123456789
_OTHER_ACCOUNT_ID = 234567890
_TOKEN = "test-stratz-token-never-log"


def _run(awaitable):
    return asyncio.run(asyncio.wait_for(awaitable, timeout=3))


def _player_row(**updates: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "steamAccountId": _ACCOUNT_ID,
        "heroId": 5,
        "isVictory": True,
        "isRadiant": False,
        "kills": 0,
        "deaths": 1,
        "assists": 2,
        "goldPerMinute": 0,
        "experiencePerMinute": 300,
        "position": "POSITION_1",
        "lane": "SAFE_LANE",
        "role": "CORE",
        "imp": None,
        "level": 0,
        "numLastHits": 100,
        "numDenies": 4,
        "providerExtension": {"nullable": None, "zero": 0},
    }
    row.update(updates)
    return row


def _match(
    game_id: int = 9001,
    start_time: int = 1_780_000_000,
    *,
    players: list[dict[str, Any]] | None = None,
    **updates: Any,
) -> dict[str, Any]:
    match: dict[str, Any] = {
        "id": game_id,
        "startDateTime": start_time,
        "durationSeconds": 2500,
        "lobbyType": "RANKED",
        "gameMode": "ALL_PICK",
        "players": [_player_row()] if players is None else players,
        "providerExtension": {"nested": [None, False, 0]},
    }
    match.update(updates)
    return match


def _response(matches: list[dict[str, Any]], *, account_id: int = _ACCOUNT_ID) -> dict[str, Any]:
    return {"data": {"player": {"steamAccountId": account_id, "matches": matches}}}


def _adapter(handler) -> StratzPlayerRecentGamesAdapter:
    transport = httpx.MockTransport(handler)
    client = StratzGraphQLClient(
        graphql_url="https://api.stratz.test/graphql",
        token=_TOKEN,
        timeout_seconds=3,
        transport=transport,
    )
    return StratzPlayerRecentGamesAdapter(client)


def test_query_sends_fixed_latest_first_single_player_request_and_limit() -> None:
    observed: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["headers"] = dict(request.headers)
        observed["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=_response([_match()]),
            request=request,
        )

    adapter = _adapter(handler)
    result = _run(adapter.get_recent_games(PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID)))

    assert observed["headers"]["authorization"] == f"Bearer {_TOKEN}"
    assert observed["body"]["query"] == PLAYER_RECENT_GAMES_QUERY
    assert observed["body"]["variables"] == {
        "steamAccountId": _ACCOUNT_ID,
        "request": {"take": 5, "orderBy": "DESC", "playerList": "SINGLE"},
    }
    assert "steamAccountId" in PLAYER_RECENT_GAMES_QUERY.split("players(", 1)[1]
    assert result.limit == 5
    assert result.games[0].valve_game_id == 9001


def test_limit_contract_defaults_to_five_and_caps_at_twenty() -> None:
    assert PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID).limit == 5
    assert PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID, limit=20).limit == 20
    with pytest.raises(ValueError):
        PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID, limit=21)


def test_maximum_limit_is_sent_without_local_overfetch() -> None:
    observed: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["variables"] = json.loads(request.content)["variables"]
        return httpx.Response(200, json=_response([]), request=request)

    adapter = _adapter(handler)
    result = _run(
        adapter.get_recent_games(PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID, limit=20))
    )

    assert observed["variables"]["request"]["take"] == 20
    assert result.games == []


def test_results_are_sorted_after_provider_selection_and_keep_source_records() -> None:
    older = _match(9001, 1_780_000_000, players=[_player_row(isVictory=False)])
    newer = _match(
        9003,
        1_780_000_300,
        players=[_player_row(isVictory=None, kills=0, goldPerMinute=None)],
    )
    middle = _match(9002, 1_780_000_100, players=[_player_row(isVictory=True)])
    source_rows = [older, newer, middle]

    adapter = _adapter(
        lambda request: httpx.Response(200, json=_response(source_rows), request=request)
    )
    result = _run(
        adapter.get_recent_games(PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID, limit=3))
    )

    assert [game.valve_game_id for game in result.games] == [9003, 9002, 9001]
    assert result.games[0].data == newer
    assert result.games[0].data["id"] == 9003
    assert result.games[0].data["players"][0]["isVictory"] is None
    assert result.games[0].data["players"][0]["goldPerMinute"] is None
    assert result.games[2].data["players"][0]["isVictory"] is False
    assert result.games[2].data["players"][0]["kills"] == 0
    assert result.games[0].data["providerExtension"] == {"nested": [None, False, 0]}
    assert result.games[0].data["players"][0]["providerExtension"] == {
        "nullable": None,
        "zero": 0,
    }
    assert result.retrieved_at.tzinfo == UTC


def test_empty_match_list_and_match_without_player_row_are_preserved() -> None:
    empty_matches = _adapter(
        lambda request: httpx.Response(200, json=_response([]), request=request)
    )
    empty_result = _run(
        empty_matches.get_recent_games(PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID))
    )

    no_player_match = _match(9010, players=[])
    no_player_adapter = _adapter(
        lambda request: httpx.Response(
            200,
            json=_response([no_player_match]),
            request=request,
        )
    )
    no_player_result = _run(
        no_player_adapter.get_recent_games(PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID))
    )

    assert empty_result.games == []
    assert no_player_result.games[0].data["players"] == []
    assert no_player_result.games[0].data["id"] == 9010


def test_null_player_is_explicitly_unavailable_not_an_empty_history() -> None:
    adapter = _adapter(
        lambda request: httpx.Response(
            200,
            json={"data": {"player": None}},
            request=request,
        )
    )

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_recent_games(PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID)))

    assert raised.value.code == "provider_error"
    assert "unavailable" in str(raised.value)


@pytest.mark.parametrize(
    ("payload", "path"),
    [
        ({}, "data"),
        ({"data": None}, "data"),
        ({"data": {}}, "data.player"),
        ({"data": {"player": {}}}, "data.player"),
        (
            {"data": {"player": {"steamAccountId": _ACCOUNT_ID}}},
            "data.player.matches",
        ),
        (
            {"data": {"player": {"steamAccountId": _ACCOUNT_ID, "matches": None}}},
            "data.player.matches",
        ),
        (
            _response([{key: value for key, value in _match().items() if key != "players"}]),
            "data.player.matches[0].players",
        ),
        (
            _response([{**_match(), "players": None}]),
            "data.player.matches[0].players",
        ),
        (
            _response([{**_match(), "players": "not-a-list"}]),
            "data.player.matches[0].players",
        ),
        (_response([[]]), "data.player.matches[0]"),
        (_response([{"id": 9001}]), "data.player.matches[0].startDateTime"),
    ],
)
def test_malformed_outer_and_match_shapes_are_schema_errors(
    payload: dict[str, Any], path: str
) -> None:
    adapter = _adapter(lambda request: httpx.Response(200, json=payload, request=request))

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_recent_games(PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID)))

    assert raised.value.code == "provider_schema_error"
    assert raised.value.details["path"] == path


@pytest.mark.parametrize(
    ("match", "path"),
    [
        (_match(0), "data.player.matches[0].id"),
        (_match(True), "data.player.matches[0].id"),
        (_match(start_time=0), "data.player.matches[0].startDateTime"),
        (_match(start_time="1780000000"), "data.player.matches[0].startDateTime"),
        (_match(start_time=10**100), "data.player.matches[0].startDateTime"),
        (_match(durationSeconds="2500"), "data.player.matches[0].durationSeconds"),
        (_match(lobbyType=1), "data.player.matches[0].lobbyType"),
        (_match(gameMode=1), "data.player.matches[0].gameMode"),
        (
            _match(players=[_player_row(isVictory=0)]),
            "data.player.matches[0].players[0].isVictory",
        ),
        (
            _match(players=[_player_row(steamAccountId=_OTHER_ACCOUNT_ID)]),
            "data.player.matches[0].players[0].steamAccountId",
        ),
        (
            _match(players=[_player_row(heroId="5")]),
            "data.player.matches[0].players[0].heroId",
        ),
        (
            _match(
                players=[{key: value for key, value in _player_row().items() if key != "heroId"}]
            ),
            "data.player.matches[0].players[0].heroId",
        ),
    ],
)
def test_invalid_match_and_player_fields_are_schema_errors(
    match: dict[str, Any], path: str
) -> None:
    adapter = _adapter(
        lambda request: httpx.Response(200, json=_response([match]), request=request)
    )

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_recent_games(PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID)))

    assert raised.value.code == "provider_schema_error"
    assert raised.value.details["path"] == path


def test_outer_identity_mismatch_and_player_row_conflicts_never_fall_back() -> None:
    mismatched_outer = _adapter(
        lambda request: httpx.Response(
            200,
            json=_response([_match()], account_id=_OTHER_ACCOUNT_ID),
            request=request,
        )
    )
    with pytest.raises(StructuredToolError) as outer_error:
        _run(
            mismatched_outer.get_recent_games(PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID))
        )
    assert outer_error.value.details["path"] == "data.player.steamAccountId"

    other_player_only = _adapter(
        lambda request: httpx.Response(
            200,
            json=_response([_match(players=[_player_row(steamAccountId=_OTHER_ACCOUNT_ID)])]),
            request=request,
        )
    )
    with pytest.raises(StructuredToolError) as row_error:
        _run(
            other_player_only.get_recent_games(PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID))
        )
    assert row_error.value.code == "provider_schema_error"
    assert row_error.value.details["path"].endswith("steamAccountId")

    conflicting_rows = _adapter(
        lambda request: httpx.Response(
            200,
            json=_response(
                [
                    _match(
                        players=[
                            _player_row(),
                            _player_row(steamAccountId=_OTHER_ACCOUNT_ID),
                        ]
                    )
                ]
            ),
            request=request,
        )
    )
    with pytest.raises(StructuredToolError) as conflict_error:
        _run(
            conflicting_rows.get_recent_games(PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID))
        )
    assert conflict_error.value.details["path"] == "data.player.matches[0].players"


def test_duplicate_or_over_limit_matches_fail_instead_of_claiming_completeness() -> None:
    duplicate_adapter = _adapter(
        lambda request: httpx.Response(
            200,
            json=_response([_match(9011), _match(9011, 1_780_000_100)]),
            request=request,
        )
    )
    with pytest.raises(StructuredToolError) as duplicate_error:
        _run(
            duplicate_adapter.get_recent_games(
                PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID, limit=2)
            )
        )
    assert duplicate_error.value.details["path"] == "data.player.matches[1].id"

    over_limit_adapter = _adapter(
        lambda request: httpx.Response(
            200,
            json=_response([_match(9012), _match(9013)]),
            request=request,
        )
    )
    with pytest.raises(StructuredToolError) as count_error:
        _run(
            over_limit_adapter.get_recent_games(
                PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID, limit=1)
            )
        )
    assert count_error.value.details["path"] == "data.player.matches"


@pytest.mark.parametrize(
    ("handler", "code"),
    [
        (
            lambda request: httpx.Response(503, text="private provider text", request=request),
            "provider_http_error",
        ),
        (
            lambda request: httpx.Response(
                200,
                json={
                    "data": {"player": {"steamAccountId": _ACCOUNT_ID}},
                    "errors": [{"message": "private"}],
                },
                request=request,
            ),
            "provider_error",
        ),
    ],
)
def test_http_and_graphql_errors_use_existing_sanitized_mapping(handler, code: str) -> None:
    adapter = _adapter(handler)

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_recent_games(PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID)))

    assert raised.value.code == code
    assert _TOKEN not in str(raised.value)
    assert "private" not in str(raised.value)


def test_provider_timeout_keeps_the_existing_timeout_error_category() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout text", request=request)

    adapter = _adapter(handler)

    with pytest.raises(StructuredToolError) as raised:
        _run(adapter.get_recent_games(PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID)))

    assert raised.value.code == "provider_timeout"
    assert "private timeout text" not in str(raised.value)


def test_stratz_game_id_composes_into_existing_game_detail_input() -> None:
    valve_id = 8960882635
    adapter = _adapter(
        lambda request: httpx.Response(
            200,
            json=_response([_match(valve_id)]),
            request=request,
        )
    )

    result = _run(adapter.get_recent_games(PlayerRecentGamesInput(steam_account_id=_ACCOUNT_ID)))
    detail_input = GameDetailInput(valve_game_id=result.games[0].valve_game_id)

    assert detail_input.valve_game_id == valve_id


def test_registry_reuses_token_gated_stratz_client_without_network_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original_graphql = StratzGraphQLClient.graphql

    async def counted_graphql(self, query, variables):
        nonlocal calls
        calls += 1
        return await original_graphql(self, query, variables)

    monkeypatch.setattr(StratzGraphQLClient, "graphql", counted_graphql)
    missing_token_registry = build_vnext_registry(settings=VNextSettings(stratz_token=""))
    settings = VNextSettings(stratz_token=_TOKEN)
    services = build_vnext_services(settings)
    registry = build_vnext_registry(services, settings=settings)

    assert "player.profile" not in {tool.name for tool in missing_token_registry.schemas()}
    assert "player.recent_games" not in {tool.name for tool in missing_token_registry.schemas()}
    assert {"player.profile", "player.recent_games"} <= {tool.name for tool in registry.schemas()}
    assert "game.detail" not in {tool.name for tool in registry.schemas()}
    profile_adapter = services.player_profile.__self__
    recent_adapter = services.player_recent_games.__self__
    assert profile_adapter.client is recent_adapter.client
    assert calls == 0


def test_recent_games_tool_schema_and_artifact_read_preserve_full_source_game() -> None:
    match = _match(9020, players=[])
    match["largeExtension"] = "x" * 15_000
    adapter = _adapter(
        lambda request: httpx.Response(200, json=_response([match]), request=request)
    )

    registry = build_vnext_registry(
        services=VNextServices(player_recent_games=adapter.get_recent_games),
        settings=VNextSettings(),
    )
    definition = registry.get("player.recent_games")
    assert definition.input_model is PlayerRecentGamesInput
    assert definition.output_model is PlayerRecentGamesResult
    assert definition.read_only is True
    assert "Steam32" in PLAYER_RECENT_GAMES_DESCRIPTION
    assert "newest first" in PLAYER_RECENT_GAMES_DESCRIPTION
    assert "does not prove" in PLAYER_RECENT_GAMES_DESCRIPTION
    assert "do not infer" in PLAYER_RECENT_GAMES_DESCRIPTION

    result = _run(
        registry.execute(
            ToolCall(
                id="recent-games",
                name="player.recent_games",
                arguments={"steam_account_id": _ACCOUNT_ID},
            )
        )
    )
    assert result.status == "ok"
    assert result.content["externalized"] is True
    ref = result.content["artifact_ref"]
    read = _run(
        registry.execute(
            ToolCall(
                id="recent-game-read",
                name="artifact.read",
                arguments={
                    "ref": ref,
                    "mode": "read",
                    "path": "games.0.data.largeExtension",
                },
            )
        )
    )
    assert read.status == "ok"
    assert read.content["value"] == "x" * 15_000
