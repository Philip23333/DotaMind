"""Validate and preserve OpenDota's full source record for one Valve game ID."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.vnext.capabilities.game.detail import GameDetailInput, GameDetailResult
from app.vnext.tools.errors import StructuredToolError

from .client import (
    OpenDotaClient,
    OpenDotaHTTPError,
    OpenDotaResponseError,
    OpenDotaTimeoutError,
    OpenDotaTransportError,
)

_MATCH_INTEGER_FIELDS = (
    "start_time",
    "duration",
    "match_seq_num",
    "lobby_type",
    "game_mode",
    "radiant_score",
    "dire_score",
)
_PLAYER_INTEGER_FIELDS = (
    "account_id",
    "player_slot",
    "hero_id",
    "level",
    "kills",
    "deaths",
    "assists",
    "gold",
    "gold_spent",
    "last_hits",
    "denies",
    "gold_per_min",
    "xp_per_min",
    "net_worth",
    "hero_damage",
    "tower_damage",
    "hero_healing",
    "win",
)
_PLAYER_STRING_FIELDS = ("personaname", "name", "localized_name")


class OpenDotaGameDetailAdapter:
    """Check response identity and known field types without narrowing source data."""

    def __init__(self, client: OpenDotaClient) -> None:
        self.client = client

    async def get_game_detail(self, query: GameDetailInput) -> GameDetailResult:
        try:
            payload = await self.client.get_match(query.valve_game_id)
        except OpenDotaTimeoutError:
            raise StructuredToolError(
                "provider_timeout",
                "OpenDota game detail request timed out",
                {"provider": "opendota"},
            ) from None
        except OpenDotaHTTPError as exc:
            category = _http_error_category(exc.status_code)
            raise StructuredToolError(
                "provider_http_error",
                "OpenDota game detail request failed",
                {
                    "provider": "opendota",
                    "status_code": exc.status_code,
                    "category": category,
                },
            ) from None
        except OpenDotaResponseError:
            raise _schema_error("response") from None
        except OpenDotaTransportError:
            raise StructuredToolError(
                "provider_error",
                "OpenDota game detail request failed",
                {"provider": "opendota"},
            ) from None

        match = _validate_match(payload, query.valve_game_id)
        try:
            return GameDetailResult(
                valve_game_id=query.valve_game_id,
                provider="opendota",
                retrieved_at=datetime.now(UTC),
                data=match,
            )
        except ValidationError:
            raise _schema_error("response") from None


def _validate_match(payload: Any, requested_id: int) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        raise _schema_error("response")
    if "error" in payload and payload["error"] is not None:
        error = payload["error"]
        if isinstance(error, (str, dict)):
            raise StructuredToolError(
                "provider_error",
                "OpenDota reported that game detail is unavailable",
                {"provider": "opendota"},
            )
        raise _schema_error("error")

    match_id = payload.get("match_id")
    if type(match_id) is not int or match_id <= 0:
        raise _schema_error("match_id")
    if match_id != requested_id:
        raise _schema_error("match_id")

    for field in _MATCH_INTEGER_FIELDS:
        if field in payload and payload[field] is not None and type(payload[field]) is not int:
            raise _schema_error(field)
    if payload.get("start_time") is not None and payload["start_time"] <= 0:
        raise _schema_error("start_time")
    if payload.get("duration") is not None and payload["duration"] < 0:
        raise _schema_error("duration")
    if "radiant_win" in payload and payload["radiant_win"] is not None:
        if type(payload["radiant_win"]) is not bool:
            raise _schema_error("radiant_win")

    players = payload.get("players")
    if players is not None:
        if not isinstance(players, list):
            raise _schema_error("players")
        for index, player in enumerate(players):
            if not isinstance(player, dict):
                raise _schema_error(f"players.{index}")
            _validate_player(player, index)
    return payload


def _validate_player(player: dict[str, Any], index: int) -> None:
    for field in _PLAYER_INTEGER_FIELDS:
        value = player.get(field)
        if field in player and value is not None and type(value) is not int:
            raise _schema_error(f"players.{index}.{field}")
    for field in _PLAYER_STRING_FIELDS:
        value = player.get(field)
        if field in player and value is not None and not isinstance(value, str):
            raise _schema_error(f"players.{index}.{field}")
    if "isRadiant" in player and player["isRadiant"] is not None:
        if type(player["isRadiant"]) is not bool:
            raise _schema_error(f"players.{index}.isRadiant")


def _http_error_category(status_code: int) -> str:
    if status_code == 404:
        return "not_found_or_unavailable"
    if status_code in {401, 403}:
        return "authentication_or_access"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "upstream_error"
    return "http_error"


def _schema_error(path: str) -> StructuredToolError:
    return StructuredToolError(
        "provider_schema_error",
        "OpenDota game detail response was invalid",
        {"provider": "opendota", "path": path},
    )


__all__ = ["OpenDotaGameDetailAdapter"]
