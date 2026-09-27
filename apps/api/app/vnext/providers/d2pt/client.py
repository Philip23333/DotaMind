"""Synchronous, source-preserving HTTP client for D2PT guide responses."""

from __future__ import annotations

import http.client
import json
import math
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from pydantic import JsonValue

from .errors import (
    D2PTHTTPError,
    D2PTJSONError,
    D2PTResponseTooLargeError,
    D2PTSchemaError,
    D2PTTimeoutError,
    D2PTTransportError,
)

_BASE_URL = "https://dota2protracker.com"
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_READ_LIMIT = _MAX_RESPONSE_BYTES + 1
_VALID_POSITIONS = {"pos 1", "pos 2", "pos 3", "pos 4", "pos 5"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://dota2protracker.com/",
    "Accept": "application/json",
}

_Opener = Callable[..., object]


@dataclass(frozen=True, repr=False)
class D2PTResponse:
    """Complete parsed response and its original bytes without a large repr."""

    raw_body: bytes
    data: list[dict[str, JsonValue]]
    retrieved_at: datetime
    content_type: str | None

    def __repr__(self) -> str:
        return (
            f"D2PTResponse(raw_body=<{len(self.raw_body)} bytes>, "
            f"data=<{len(self.data)} records>, retrieved_at={self.retrieved_at!r}, "
            f"content_type={self.content_type!r})"
        )


class D2PTClient:
    """Fetch and minimally validate D2PT source responses, with no retries."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        opener: _Opener | None = None,
    ) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise ValueError("D2PT timeout must be a finite positive number")
        try:
            is_finite = math.isfinite(timeout_seconds)
        except (OverflowError, TypeError):
            is_finite = False
        if not is_finite or timeout_seconds <= 0:
            raise ValueError("D2PT timeout must be a finite positive number")

        self.timeout_seconds = float(timeout_seconds)
        self._opener = urllib.request.urlopen if opener is None else opener

    def heroes_list(self) -> D2PTResponse:
        return self._get_json_array(
            "/api/heroes/list",
            validate=_validate_heroes_list,
        )

    def pub_builds(self, hero_id: int, position: int) -> D2PTResponse:
        _validate_hero_id(hero_id)
        _validate_position(position)
        position_name = urllib.parse.quote(f"pos {position}", safe="")
        return self._get_json_array(
            f"/api/hero/{hero_id}/builds?position={position_name}",
            validate=lambda rows: _validate_pub_rows(rows, hero_id, f"pos {position}"),
        )

    def pro_builds(self, hero_id: int) -> D2PTResponse:
        _validate_hero_id(hero_id)
        return self._get_json_array(
            f"/api/hero/{hero_id}/pro-builds",
            validate=lambda rows: _validate_pro_rows(rows, hero_id),
        )

    def _get_json_array(
        self,
        path: str,
        *,
        validate: Callable[[list[dict[str, JsonValue]]], None],
    ) -> D2PTResponse:
        request = urllib.request.Request(
            f"{_BASE_URL}{path}",
            headers=HEADERS,
            method="GET",
        )
        try:
            response = self._opener(request, timeout=self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            retry_after = _get_header(exc.headers, "Retry-After")
            try:
                exc.close()
            finally:
                raise D2PTHTTPError(status_code, retry_after) from None
        except (TimeoutError, urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            _raise_transport_error(exc)

        try:
            status_code = response.getcode()  # type: ignore[attr-defined]
            if type(status_code) is not int:
                raise D2PTTransportError() from None
            if status_code != 200:
                raise D2PTHTTPError(
                    status_code,
                    _get_header(response.headers, "Retry-After"),  # type: ignore[attr-defined]
                )

            content_type = _get_header(response.headers, "Content-Type")  # type: ignore[attr-defined]
            try:
                raw_body = response.read(_READ_LIMIT)  # type: ignore[attr-defined]
            except (TimeoutError, urllib.error.URLError, OSError, http.client.HTTPException) as exc:
                _raise_transport_error(exc)
            if not isinstance(raw_body, bytes):
                raise D2PTTransportError() from None
            if len(raw_body) > _MAX_RESPONSE_BYTES:
                raise D2PTResponseTooLargeError()
            retrieved_at = datetime.now(UTC)
        except (TimeoutError, urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            _raise_transport_error(exc)
        finally:
            response.close()  # type: ignore[attr-defined]

        data = _decode_json_array(raw_body)
        validate(data)
        return D2PTResponse(
            raw_body=raw_body,
            data=data,
            retrieved_at=retrieved_at,
            content_type=content_type,
        )


def _validate_hero_id(hero_id: object) -> None:
    if type(hero_id) is not int or hero_id <= 0:
        raise ValueError("hero_id must be a positive integer")


def _validate_position(position: object) -> None:
    if type(position) is not int or not 1 <= position <= 5:
        raise ValueError("position must be an integer from 1 through 5")


def _validate_heroes_list(rows: list[dict[str, JsonValue]]) -> None:
    if not rows:
        raise D2PTSchemaError("heroes_empty")

    seen: set[int] = set()
    for row in rows:
        hero_id = row.get("hero_id")
        if type(hero_id) is not int or hero_id <= 0:
            raise D2PTSchemaError("invalid_hero_id")
        if hero_id in seen:
            raise D2PTSchemaError("duplicate_hero_id")
        seen.add(hero_id)


def _validate_pub_rows(
    rows: list[dict[str, JsonValue]],
    requested_hero_id: int,
    requested_position: str,
) -> None:
    for row in rows:
        hero_id = row.get("hero_id")
        if type(hero_id) is not int:
            raise D2PTSchemaError("invalid_hero_id")
        if hero_id != requested_hero_id:
            raise D2PTSchemaError("hero_mismatch")
        if row.get("position") != requested_position:
            raise D2PTSchemaError("invalid_position")
        if not isinstance(row.get("build_data"), dict):
            raise D2PTSchemaError("invalid_build_data")


def _validate_pro_rows(
    rows: list[dict[str, JsonValue]],
    requested_hero_id: int,
) -> None:
    for row in rows:
        hero_id = row.get("hero_id")
        if type(hero_id) is not int:
            raise D2PTSchemaError("invalid_hero_id")
        if hero_id != requested_hero_id:
            raise D2PTSchemaError("hero_mismatch")
        position = row.get("position")
        if not isinstance(position, str) or position not in _VALID_POSITIONS:
            raise D2PTSchemaError("invalid_position")

        recent_matches = row.get("recent_matches")
        if recent_matches is not None:
            if not isinstance(recent_matches, list):
                raise D2PTSchemaError("invalid_recent_matches")
            if any(not isinstance(match, dict) for match in recent_matches):
                raise D2PTSchemaError("invalid_recent_matches")


def _decode_json_array(raw_body: bytes) -> list[dict[str, JsonValue]]:
    try:
        text = raw_body.decode("utf-8-sig")
        payload = json.loads(
            text,
            parse_constant=_reject_json_constant,
            parse_float=_parse_finite_float,
        )
    except (UnicodeDecodeError, ValueError):
        raise D2PTJSONError() from None

    if not isinstance(payload, list):
        raise D2PTSchemaError("invalid_root")
    if any(not isinstance(row, dict) for row in payload):
        raise D2PTSchemaError("invalid_record")
    return cast(list[dict[str, JsonValue]], payload)


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite number")
    return parsed


def _reject_json_constant(_: str) -> None:
    raise ValueError("non-finite JSON constant")


def _get_header(headers: object, name: str) -> str | None:
    if headers is None or not hasattr(headers, "get"):
        return None
    value = headers.get(name)  # type: ignore[attr-defined]
    return value if isinstance(value, str) else None


def _raise_transport_error(exc: BaseException) -> None:
    if _contains_timeout(exc):
        raise D2PTTimeoutError() from None
    raise D2PTTransportError() from None


def _contains_timeout(exc: BaseException) -> bool:
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, (TimeoutError, socket.timeout)):
            return True
        reason = getattr(current, "reason", None)
        if isinstance(reason, BaseException):
            pending.append(reason)
        cause = current.__cause__
        if cause is not None:
            pending.append(cause)
    return False


__all__ = ["D2PTClient", "D2PTResponse", "HEADERS"]
