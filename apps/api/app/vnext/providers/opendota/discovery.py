"""Read complete, validated OpenDota League collections for internal use."""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from typing import Any, cast

from pydantic import JsonValue

from app.vnext.providers.source_reads import read_source
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
    "radiant_team_id",
    "dire_team_id",
    "leagueid",
    "series_id",
    "series_type",
)
_MATCH_NAME_FIELDS = (
    "radiant_team_name",
    "dire_team_name",
    "radiant_name",
    "dire_name",
)


class OpenDotaDiscoveryAdapter:
    """Expose source-shaped League and single-game collection records."""

    def __init__(self, client: OpenDotaClient) -> None:
        self.client = client

    async def get_leagues(self) -> list[dict[str, JsonValue]]:
        return await read_source(self, "leagues", None, self._get_leagues)

    async def _get_leagues(self) -> list[dict[str, JsonValue]]:
        payload = await self._request(self.client.get_leagues)
        return _validate_leagues(payload)

    async def get_league_matches(self, league_id: int) -> list[dict[str, JsonValue]]:
        if type(league_id) is not int or league_id <= 0:
            raise ValueError("OpenDota league_id must be a positive integer")
        return await read_source(
            self, "league_matches", league_id, lambda: self._get_league_matches(league_id)
        )

    async def _get_league_matches(self, league_id: int) -> list[dict[str, JsonValue]]:
        payload = await self._request(
            lambda: self.client.get_league_matches(league_id)
        )
        return _validate_league_matches(payload, league_id)

    async def _request(self, call: Callable[[], Awaitable[Any]]) -> Any:
        try:
            return await call()
        except OpenDotaTimeoutError:
            raise StructuredToolError(
                "provider_timeout",
                "OpenDota discovery request timed out",
                {"provider": "opendota"},
            ) from None
        except OpenDotaHTTPError as exc:
            raise StructuredToolError(
                "provider_http_error",
                "OpenDota discovery request failed",
                {
                    "provider": "opendota",
                    "status_code": exc.status_code,
                    "category": _http_error_category(exc.status_code),
                },
            ) from None
        except OpenDotaResponseError:
            raise _schema_error("response") from None
        except OpenDotaTransportError:
            raise StructuredToolError(
                "provider_error",
                "OpenDota discovery request failed",
                {"provider": "opendota"},
            ) from None


def _validate_leagues(payload: Any) -> list[dict[str, JsonValue]]:
    rows = _collection(payload)
    for index, row in enumerate(rows):
        path = f"response[{index}]"
        _validate_json_value(row, path)
        league_id = row.get("leagueid")
        if type(league_id) is not int or league_id <= 0:
            raise _schema_error(f"{path}.leagueid")
        if not isinstance(row.get("name"), str):
            raise _schema_error(f"{path}.name")
    return cast(list[dict[str, JsonValue]], rows)


def _validate_league_matches(
    payload: Any,
    requested_league_id: int,
) -> list[dict[str, JsonValue]]:
    rows = _collection(payload)
    for index, row in enumerate(rows):
        path = f"response[{index}]"
        _validate_json_value(row, path)
        match_id = row.get("match_id")
        if type(match_id) is not int or match_id <= 0:
            raise _schema_error(f"{path}.match_id")

        for field in _MATCH_INTEGER_FIELDS:
            value = row.get(field)
            if field in row and value is not None and type(value) is not int:
                raise _schema_error(f"{path}.{field}")
        for field in _MATCH_NAME_FIELDS:
            value = row.get(field)
            if field in row and value is not None and not isinstance(value, str):
                raise _schema_error(f"{path}.{field}")
        if "radiant_win" in row and row["radiant_win"] is not None:
            if type(row["radiant_win"]) is not bool:
                raise _schema_error(f"{path}.radiant_win")

        league_id = row.get("leagueid")
        if league_id is not None and league_id != requested_league_id:
            raise _schema_error(f"{path}.leagueid")
    return cast(list[dict[str, JsonValue]], rows)


def _collection(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise _schema_error("response")
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise _schema_error(f"response[{index}]")
        rows.append(row)
    return rows


def _validate_json_value(value: Any, path: str) -> None:
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is float:
        if math.isfinite(value):
            return
        raise _schema_error(path)
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _schema_error(path)
            _validate_json_value(item, f"{path}.{key}")
        return
    raise _schema_error(path)


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
        "OpenDota discovery response was invalid",
        {"provider": "opendota", "path": path},
    )


__all__ = ["OpenDotaDiscoveryAdapter"]
