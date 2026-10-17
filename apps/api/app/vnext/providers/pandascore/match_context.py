"""Read and validate complete PandaScore match context for internal use."""

from __future__ import annotations

import json
import math
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, cast

import httpx
from pydantic import JsonValue

from app.vnext.providers.source_reads import read_source
from app.vnext.tools.errors import StructuredToolError

from .client import (
    PandaScoreClient,
    PandaScoreConfigurationError,
    PandaScoreProtocolError,
)

_MATCH_ID_FIELDS = ("league_id", "serie_id", "tournament_id", "winner_id")
_MATCH_INTEGER_FIELDS = (*_MATCH_ID_FIELDS, "number_of_games")
_MATCH_TEXT_FIELDS = (
    "name",
    "slug",
    "status",
    "match_type",
    "winner_type",
)
_MATCH_DATETIME_FIELDS = (
    "begin_at",
    "end_at",
    "scheduled_at",
    "original_scheduled_at",
    "modified_at",
)
_MATCH_BOOLEAN_FIELDS = ("draw", "forfeit", "rescheduled")
_NESTED_COMPETITION_TEXT_FIELDS = (
    "name",
    "full_name",
    "slug",
    "season",
    "tier",
)
_TEAM_TEXT_FIELDS = ("name", "acronym", "location", "slug", "image_url", "type")
_GAME_INTEGER_FIELDS = ("length", "winner_id", "match_id")
_GAME_TEXT_FIELDS = ("status", "winner_type")
_GAME_DATETIME_FIELDS = ("begin_at", "end_at")
_GAME_BOOLEAN_FIELDS = ("complete", "finished", "forfeit")


class PandaScoreMatchContextAdapter:
    """Fetch one exact Match while preserving its complete validated source row."""

    def __init__(self, client: PandaScoreClient) -> None:
        self.client = client

    async def get_match_context(self, match_id: int) -> dict[str, JsonValue] | None:
        if type(match_id) is not int or match_id <= 0:
            raise ValueError("match_id must be a positive integer")

        return await read_source(
            self, "match_context", match_id, lambda: self._get_match_context(match_id)
        )

    async def _get_match_context(self, match_id: int) -> dict[str, JsonValue] | None:

        rows = await self._request(
            lambda: self.client.get_list(
                "/dota2/matches",
                params={"filter[id]": match_id, "page": 1, "per_page": 2},
            )
        )
        if not isinstance(rows, list):
            raise _schema_error("response")
        if not rows:
            return None
        if len(rows) != 1:
            raise _schema_error("response")

        row = rows[0]
        if not isinstance(row, dict):
            raise _schema_error("response[0]")
        _validate_match(row, match_id)
        return cast(dict[str, JsonValue], row)

    async def _request(
        self,
        call: Callable[[], Awaitable[list[Any]]],
    ) -> list[Any]:
        try:
            return await call()
        except PandaScoreConfigurationError:
            raise StructuredToolError(
                "configuration_error",
                "PandaScore match context requires a configured token",
                {"provider": "pandascore"},
            ) from None
        except httpx.TimeoutException:
            raise StructuredToolError(
                "provider_timeout",
                "PandaScore match context request timed out",
                {"provider": "pandascore"},
            ) from None
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            raise StructuredToolError(
                "provider_http_error",
                "PandaScore match context request failed",
                {
                    "provider": "pandascore",
                    "status_code": status_code,
                    "category": _http_error_category(status_code),
                },
            ) from None
        except PandaScoreProtocolError:
            raise _schema_error("response") from None
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise _schema_error("response") from None
        except httpx.HTTPError:
            raise StructuredToolError(
                "provider_error",
                "PandaScore match context request failed",
                {"provider": "pandascore", "category": "transport_error"},
            ) from None


def _validate_match(row: dict[str, Any], requested_id: int) -> None:
    _validate_json_value(row, "response[0]")
    match_id = row.get("id")
    if type(match_id) is not int or match_id <= 0:
        raise _schema_error("response[0].id")
    if match_id != requested_id:
        raise _schema_error("response[0].id")

    _validate_optional_types(
        row,
        _MATCH_INTEGER_FIELDS,
        int,
        "response[0]",
    )
    _validate_optional_types(row, _MATCH_TEXT_FIELDS, str, "response[0]")
    _validate_optional_types(row, _MATCH_BOOLEAN_FIELDS, bool, "response[0]")
    for field in _MATCH_DATETIME_FIELDS:
        _validate_datetime(row, field, "response[0]")

    for field in ("league", "serie", "tournament"):
        _validate_competition(row, field, "response[0]")
    _validate_team_relation(row, "winner", "response[0]")
    _validate_opponents(row.get("opponents", _MISSING), "response[0]")
    _validate_results(row.get("results", _MISSING), "response[0]")
    _validate_games(row.get("games", _MISSING), requested_id, "response[0]")


_MISSING = object()


def _validate_optional_types(
    record: dict[str, Any],
    fields: tuple[str, ...],
    expected_type: type,
    path: str,
) -> None:
    for field in fields:
        value = record.get(field)
        if field in record and value is not None and type(value) is not expected_type:
            raise _schema_error(f"{path}.{field}")


def _validate_datetime(record: dict[str, Any], field: str, path: str) -> None:
    value = record.get(field)
    if field not in record or value is None:
        return
    if not isinstance(value, str):
        raise _schema_error(f"{path}.{field}")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise _schema_error(f"{path}.{field}") from None


def _validate_competition(record: dict[str, Any], field: str, path: str) -> None:
    value = record.get(field, _MISSING)
    if value is _MISSING or value is None:
        return
    nested_path = f"{path}.{field}"
    if not isinstance(value, dict):
        raise _schema_error(nested_path)
    _validate_positive_id(value, "id", nested_path)
    _validate_optional_types(
        value,
        _NESTED_COMPETITION_TEXT_FIELDS,
        str,
        nested_path,
    )
    year = value.get("year")
    if "year" in value and year is not None and type(year) is not int:
        raise _schema_error(f"{nested_path}.year")


def _validate_team_relation(record: dict[str, Any], field: str, path: str) -> None:
    value = record.get(field, _MISSING)
    if value is _MISSING or value is None:
        return
    nested_path = f"{path}.{field}"
    if not isinstance(value, dict):
        raise _schema_error(nested_path)
    _validate_team(value, nested_path)


def _validate_team(team: dict[str, Any], path: str) -> None:
    _validate_positive_id(team, "id", path)
    _validate_optional_types(team, _TEAM_TEXT_FIELDS, str, path)


def _validate_positive_id(record: dict[str, Any], field: str, path: str) -> None:
    value = record.get(field)
    if field in record and value is not None and (type(value) is not int or value <= 0):
        raise _schema_error(f"{path}.{field}")


def _validate_opponents(value: Any, path: str) -> None:
    if value is _MISSING or value is None:
        return
    field_path = f"{path}.opponents"
    if not isinstance(value, list):
        raise _schema_error(field_path)
    for index, wrapper in enumerate(value):
        item_path = f"{field_path}[{index}]"
        if not isinstance(wrapper, dict):
            raise _schema_error(item_path)
        opponent = wrapper.get("opponent", _MISSING)
        if opponent is _MISSING or opponent is None:
            continue
        if not isinstance(opponent, dict):
            raise _schema_error(f"{item_path}.opponent")
        _validate_team(opponent, f"{item_path}.opponent")


def _validate_results(value: Any, path: str) -> None:
    if value is _MISSING or value is None:
        return
    field_path = f"{path}.results"
    if not isinstance(value, list):
        raise _schema_error(field_path)
    for index, result in enumerate(value):
        item_path = f"{field_path}[{index}]"
        if not isinstance(result, dict):
            raise _schema_error(item_path)
        for field in ("team_id", "score"):
            item = result.get(field)
            if field in result and item is not None and type(item) is not int:
                raise _schema_error(f"{item_path}.{field}")


def _validate_games(value: Any, match_id: int, path: str) -> None:
    if value is _MISSING or value is None:
        return
    field_path = f"{path}.games"
    if not isinstance(value, list):
        raise _schema_error(field_path)
    for index, game in enumerate(value):
        game_path = f"{field_path}[{index}]"
        if not isinstance(game, dict):
            raise _schema_error(game_path)
        for field in ("id", "position"):
            field_value = game.get(field)
            if type(field_value) is not int or field_value <= 0:
                raise _schema_error(f"{game_path}.{field}")

        _validate_optional_types(game, _GAME_INTEGER_FIELDS, int, game_path)
        _validate_optional_types(game, _GAME_TEXT_FIELDS, str, game_path)
        _validate_optional_types(game, _GAME_BOOLEAN_FIELDS, bool, game_path)
        for field in _GAME_DATETIME_FIELDS:
            _validate_datetime(game, field, game_path)

        nested_match_id = game.get("match_id")
        if nested_match_id is not None and nested_match_id != match_id:
            raise _schema_error(f"{game_path}.match_id")
        _validate_team_relation(game, "winner", game_path)


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
        "PandaScore match context response was invalid",
        {"provider": "pandascore", "path": path},
    )


__all__ = ["PandaScoreMatchContextAdapter"]
