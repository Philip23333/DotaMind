"""Small value readers shared by the OpenDota game-detail projections."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from app.vnext.capabilities.game.data import CoverageData, MissingData


def _missing(coverage: CoverageData, path: str, reason: str) -> None:
    entry = MissingData(path=path, reason=reason)
    if entry not in coverage.missing:
        coverage.missing.append(entry)


def _is_number(value: Any) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _value(
    source: Mapping[str, Any], key: str, kind: type, path: str,
    coverage: CoverageData, *, required: bool = True,
) -> Any:
    value = source.get(key)
    valid = _is_number(value) if kind is float else type(value) is kind
    if valid:
        return value
    if required:
        _missing(coverage, path, f"Source {key} is unavailable or invalid")
    return None


def _rows(value: Any, path: str, coverage: CoverageData) -> list[dict[str, Any]] | None:
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    _missing(coverage, path, "Source record list is unavailable or invalid")
    return None
