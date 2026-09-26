"""STRATZ-backed profile lookup for one Steam32 account."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.vnext.capabilities.player.profile import PlayerProfileInput, PlayerProfileResult
from app.vnext.tools.errors import StructuredToolError

from .client import (
    StratzGraphQLClient,
    StratzGraphQLError,
    StratzHTTPError,
    StratzResponseError,
    StratzTimeoutError,
    StratzTransportError,
)

PLAYER_PROFILE_QUERY = """\
query PlayerProfile($steamAccountId: Long!) {
  player(steamAccountId: $steamAccountId) {
    steamAccountId
    matchCount
    winCount
    imp
    firstMatchDate
    lastMatchDate
    steamAccount {
      id
      name
      avatar
      seasonRank
      smurfFlag
      proSteamAccount {
        name
      }
    }
  }
}
"""

_INTEGER_FIELDS = (
    "matchCount",
    "winCount",
    "imp",
    "firstMatchDate",
    "lastMatchDate",
)
_OPTIONAL_STRING_FIELDS = ("name", "avatar")
_OPTIONAL_INTEGER_FIELDS = ("seasonRank", "smurfFlag")


class StratzPlayerProfileAdapter:
    def __init__(self, client: StratzGraphQLClient) -> None:
        self.client = client

    async def get_profile(self, query: PlayerProfileInput) -> PlayerProfileResult:
        try:
            payload = await self.client.graphql(
                PLAYER_PROFILE_QUERY,
                {"steamAccountId": query.steam_account_id},
            )
        except StratzTimeoutError:
            raise StructuredToolError(
                "provider_timeout",
                "STRATZ player profile request timed out",
                {"provider": "stratz"},
            ) from None
        except StratzHTTPError as exc:
            raise StructuredToolError(
                "provider_http_error",
                "STRATZ player profile request failed",
                {"provider": "stratz", "status_code": exc.status_code},
            ) from None
        except StratzGraphQLError:
            raise StructuredToolError(
                "provider_error",
                "STRATZ player profile query returned errors",
                {"provider": "stratz"},
            ) from None
        except StratzResponseError as exc:
            raise _schema_error(exc.path) from None
        except StratzTransportError:
            raise StructuredToolError(
                "provider_error",
                "STRATZ player profile request failed",
                {"provider": "stratz"},
            ) from None

        player = _player_from_response(payload, query.steam_account_id)
        return PlayerProfileResult(
            steam_account_id=query.steam_account_id,
            provider="stratz",
            retrieved_at=datetime.now(UTC),
            found=player is not None,
            profile=player,
        )


def _player_from_response(
    payload: dict[str, Any],
    requested_id: int,
) -> dict[str, Any] | None:
    if "data" not in payload or not isinstance(payload["data"], dict):
        raise _schema_error("data")
    data = payload["data"]
    if "player" not in data:
        raise _schema_error("data.player")
    player = data["player"]
    if player is None:
        return None
    if not isinstance(player, dict) or not player:
        raise _schema_error("data.player")

    returned_id = player.get("steamAccountId")
    if type(returned_id) is not int:
        raise _schema_error("data.player.steamAccountId")
    if returned_id != requested_id:
        raise StructuredToolError(
            "provider_schema_error",
            "STRATZ player profile identity did not match the requested account",
            {"provider": "stratz", "path": "data.player.steamAccountId"},
        )

    for field in _INTEGER_FIELDS:
        if field in player and player[field] is not None and type(player[field]) is not int:
            raise _schema_error(f"data.player.{field}")

    account = player.get("steamAccount")
    if account is not None:
        if not isinstance(account, dict):
            raise _schema_error("data.player.steamAccount")
        if "id" in account and account["id"] is not None and type(account["id"]) is not int:
            raise _schema_error("data.player.steamAccount.id")
        for field in _OPTIONAL_STRING_FIELDS:
            if field in account and account[field] is not None and not isinstance(
                account[field], str
            ):
                raise _schema_error(f"data.player.steamAccount.{field}")
        for field in _OPTIONAL_INTEGER_FIELDS:
            if field in account and account[field] is not None and type(account[field]) is not int:
                raise _schema_error(f"data.player.steamAccount.{field}")
        professional = account.get("proSteamAccount")
        if professional is not None:
            if not isinstance(professional, dict):
                raise _schema_error("data.player.steamAccount.proSteamAccount")
            name = professional.get("name")
            if name is not None and not isinstance(name, str):
                raise _schema_error("data.player.steamAccount.proSteamAccount.name")

    return player


def _schema_error(path: str) -> StructuredToolError:
    return StructuredToolError(
        "provider_schema_error",
        "STRATZ player profile response was invalid",
        {"provider": "stratz", "path": path},
    )


__all__ = ["PLAYER_PROFILE_QUERY", "StratzPlayerProfileAdapter"]
