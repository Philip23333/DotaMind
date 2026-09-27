"""STRATZ-backed recent-game lookup for one exact Steam32 account."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.vnext.capabilities.player.recent_games import (
    PlayerRecentGame,
    PlayerRecentGamesInput,
    PlayerRecentGamesResult,
)
from app.vnext.tools.errors import StructuredToolError

from .client import (
    StratzGraphQLClient,
    StratzGraphQLError,
    StratzHTTPError,
    StratzResponseError,
    StratzTimeoutError,
    StratzTransportError,
)

PLAYER_RECENT_GAMES_QUERY = """\
query PlayerRecentGames(
  $steamAccountId: Long!,
  $request: PlayerMatchesRequestType!
) {
  player(steamAccountId: $steamAccountId) {
    steamAccountId
    matches(request: $request) {
      id
      startDateTime
      durationSeconds
      lobbyType
      gameMode
      players(steamAccountId: $steamAccountId) {
        steamAccountId
        heroId
        isVictory
        isRadiant
        kills
        deaths
        assists
        goldPerMinute
        experiencePerMinute
        position
        lane
        role
        imp
        level
        numLastHits
        numDenies
      }
    }
  }
}
"""

_MATCH_REQUIRED_FIELDS = ("durationSeconds", "lobbyType", "gameMode", "players")
_PLAYER_INTEGER_FIELDS = (
    "heroId",
    "kills",
    "deaths",
    "assists",
    "goldPerMinute",
    "experiencePerMinute",
    "imp",
    "level",
    "numLastHits",
    "numDenies",
)
_PLAYER_BOOLEAN_FIELDS = ("isVictory", "isRadiant")
_PLAYER_ENUM_FIELDS = ("position", "lane", "role")


class StratzPlayerRecentGamesAdapter:
    """Query a bounded latest-first match sample and preserve its source records."""

    def __init__(self, client: StratzGraphQLClient) -> None:
        self.client = client

    async def get_recent_games(
        self,
        query: PlayerRecentGamesInput,
    ) -> PlayerRecentGamesResult:
        request = {
            "take": query.limit,
            "orderBy": "DESC",
            "playerList": "SINGLE",
        }
        try:
            payload = await self.client.graphql(
                PLAYER_RECENT_GAMES_QUERY,
                {"steamAccountId": query.steam_account_id, "request": request},
            )
        except StratzTimeoutError:
            raise StructuredToolError(
                "provider_timeout",
                "STRATZ player recent-games request timed out",
                {"provider": "stratz"},
            ) from None
        except StratzHTTPError as exc:
            raise StructuredToolError(
                "provider_http_error",
                "STRATZ player recent-games request failed",
                {"provider": "stratz", "status_code": exc.status_code},
            ) from None
        except StratzGraphQLError:
            raise StructuredToolError(
                "provider_error",
                "STRATZ player recent-games query returned errors",
                {"provider": "stratz"},
            ) from None
        except StratzResponseError as exc:
            raise _schema_error(exc.path) from None
        except StratzTransportError:
            raise StructuredToolError(
                "provider_error",
                "STRATZ player recent-games request failed",
                {"provider": "stratz"},
            ) from None

        matches = _matches_from_response(payload, query.steam_account_id, query.limit)
        matches.sort(key=lambda item: (item["startDateTime"], item["id"]), reverse=True)
        return PlayerRecentGamesResult(
            steam_account_id=query.steam_account_id,
            provider="stratz",
            retrieved_at=datetime.now(UTC),
            limit=query.limit,
            games=[PlayerRecentGame(valve_game_id=match["id"], data=match) for match in matches],
        )


def _matches_from_response(
    payload: dict[str, Any],
    requested_id: int,
    limit: int,
) -> list[dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise _schema_error("data")
    if "player" not in data:
        raise _schema_error("data.player")
    player = data["player"]
    if player is None:
        raise StructuredToolError(
            "provider_error",
            "STRATZ player data is unavailable for this recent-games query",
            {"provider": "stratz"},
        )
    if not isinstance(player, dict) or not player:
        raise _schema_error("data.player")

    returned_id = player.get("steamAccountId")
    if type(returned_id) is not int:
        raise _schema_error("data.player.steamAccountId")
    if returned_id != requested_id:
        raise _schema_error("data.player.steamAccountId")
    matches = player.get("matches")
    if not isinstance(matches, list):
        raise _schema_error("data.player.matches")
    if len(matches) > limit:
        raise _schema_error("data.player.matches")

    seen_ids: set[int] = set()
    validated: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        path = f"data.player.matches[{index}]"
        if not isinstance(match, dict) or not match:
            raise _schema_error(path)
        _require_fields(match, ("id", "startDateTime", *_MATCH_REQUIRED_FIELDS), path)

        game_id = match["id"]
        if type(game_id) is not int or game_id <= 0:
            raise _schema_error(f"{path}.id")
        if game_id in seen_ids:
            raise _schema_error(f"{path}.id")
        seen_ids.add(game_id)

        start_time = match["startDateTime"]
        if type(start_time) is not int or start_time <= 0:
            raise _schema_error(f"{path}.startDateTime")
        try:
            datetime.fromtimestamp(start_time, tz=UTC)
        except (OverflowError, OSError, ValueError):
            raise _schema_error(f"{path}.startDateTime") from None

        duration = match["durationSeconds"]
        if duration is not None and (type(duration) is not int or duration < 0):
            raise _schema_error(f"{path}.durationSeconds")
        for field in ("lobbyType", "gameMode"):
            value = match[field]
            if value is not None and not isinstance(value, str):
                raise _schema_error(f"{path}.{field}")

        rows = match["players"]
        if not isinstance(rows, list):
            raise _schema_error(f"{path}.players")
        if len(rows) > 1:
            raise _schema_error(f"{path}.players")
        for row_index, row in enumerate(rows):
            row_path = f"{path}.players[{row_index}]"
            if not isinstance(row, dict) or not row:
                raise _schema_error(row_path)
            _require_fields(
                row,
                (
                    "steamAccountId",
                    *_PLAYER_INTEGER_FIELDS,
                    *_PLAYER_BOOLEAN_FIELDS,
                    *_PLAYER_ENUM_FIELDS,
                ),
                row_path,
            )
            row_account_id = row["steamAccountId"]
            if type(row_account_id) is not int or row_account_id != requested_id:
                raise _schema_error(f"{row_path}.steamAccountId")
            for field in _PLAYER_INTEGER_FIELDS:
                value = row[field]
                if value is not None and type(value) is not int:
                    raise _schema_error(f"{row_path}.{field}")
            for field in _PLAYER_BOOLEAN_FIELDS:
                value = row[field]
                if value is not None and type(value) is not bool:
                    raise _schema_error(f"{row_path}.{field}")
            for field in _PLAYER_ENUM_FIELDS:
                value = row[field]
                if value is not None and not isinstance(value, str):
                    raise _schema_error(f"{row_path}.{field}")
        validated.append(match)
    return validated


def _require_fields(record: dict[str, Any], fields: tuple[str, ...], path: str) -> None:
    for field in fields:
        if field not in record:
            raise _schema_error(f"{path}.{field}")


def _schema_error(path: str) -> StructuredToolError:
    return StructuredToolError(
        "provider_schema_error",
        "STRATZ player recent-games response was invalid",
        {"provider": "stratz", "path": path},
    )


__all__ = ["PLAYER_RECENT_GAMES_QUERY", "StratzPlayerRecentGamesAdapter"]
