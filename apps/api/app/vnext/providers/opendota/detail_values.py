"""Small value readers shared by the OpenDota game-detail projections."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from app.vnext.capabilities.game.data import CoverageData, MissingData

ABSENT = object()


def _missing(
    coverage: CoverageData, path: str, reason: str, *,
    source_path: str | None = None, source_value: Any = ABSENT,
) -> None:
    evidence = {}
    if source_path is not None and (
        source_value is None or type(source_value) in (str, bool) or _is_number(source_value)
    ):
        evidence = {"source_path": source_path, "source_value": source_value}
    entry = MissingData(path=path, reason=reason, **evidence)
    if entry not in coverage.missing:
        coverage.missing.append(entry)


def _is_number(value: Any) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _hero_id(key: Any, hero_ids: Mapping[str, int]) -> int | None:
    if not isinstance(key, str) or not key.startswith("npc_dota_hero_"):
        return None
    value = hero_ids.get(key)
    return value if type(value) is int and value > 0 else None


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
