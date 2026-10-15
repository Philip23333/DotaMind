"""Source-aligned minute observations and unmodified team advantage series."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping
from typing import Any

from app.vnext.capabilities.game.data import CoverageData, EconomyData, MinuteData

from .detail_values import _is_number, _missing

_MINUTE_FIELDS = {
    "net_worth": "networth_t", "earned_gold": "gold_t", "experience": "xp_t",
    "last_hits": "lh_t", "denies": "dn_t",
}


def _axis(value: Any) -> list[int] | None:
    if not isinstance(value, list) or not all(type(t) is int for t in value):
        return None
    if any(left >= right for left, right in zip(value, value[1:], strict=False)):
        return None
    return value


def _series(value: Any, path: str, coverage: CoverageData) -> list | None:
    if not isinstance(value, list):
        _missing(coverage, path, "Source series is unavailable or invalid")
        return None
    result = [item if _is_number(item) else None for item in value]
    if any(item is None for item in result):
        _missing(coverage, path, "Some source samples are unavailable or invalid")
    return result


def _counts(value: Any, axis: list[int], path: str, coverage: CoverageData) -> list | None:
    if not isinstance(value, list) or any(
        not isinstance(row, dict) or not _is_number(row.get("time")) for row in value
    ):
        _missing(coverage, path, "Source event log is unavailable or has invalid event times")
        return None
    event_times = sorted(row["time"] for row in value)
    return [bisect_right(event_times, time) for time in axis]


def project_minutes(
    player: Mapping[str, Any], index: int, coverage: CoverageData,
) -> list[MinuteData] | None:
    path = f"players[{index}].minute_timeline"
    axis = _axis(player.get("times"))
    if axis is None:
        _missing(coverage, path, "Source times is unavailable or is not a strictly increasing axis")
        return None
    columns = {}
    for field, source in _MINUTE_FIELDS.items():
        values = _series(player.get(source), f"{path}.{field}", coverage)
        if values is not None and len(values) != len(axis):
            _missing(coverage, f"{path}.{field}", "Source series length differs from times")
            values = None
        columns[field] = values
    for field, log in (("kills", "kills_log"), ("deaths", "deaths_log")):
        columns[field] = _counts(player.get(log), axis, f"{path}.{field}", coverage)
    return [MinuteData(
        time_seconds=time,
        **{field: None if values is None else values[i] for field, values in columns.items()},
    ) for i, time in enumerate(axis)]


def project_economy(
    source: Mapping[str, Any], players: list[dict] | None, coverage: CoverageData,
) -> EconomyData:
    fields = {key: _series(source.get(key), f"economy.{key}", coverage)
              for key in ("radiant_gold_adv", "radiant_xp_adv")}
    axes = [_axis(player.get("times")) for player in players] if players else []
    axis = axes[0] if axes else None
    # OpenDota documents team advantages at each minute. Reuse an observed
    # player axis only if all axes agree with its zero-based minute buckets.
    # Never synthesize an axis merely from the advantage-array length.
    aligned = (
        axis is not None and all(other == axis for other in axes)
        and all(time == i * 60 for i, time in enumerate(axis))
        and all(values is not None and len(values) == len(axis) for values in fields.values())
    )
    if not aligned:
        axis = None
        _missing(coverage, "economy.time_seconds",
                 "Cannot establish a shared source minute axis for both advantage series")
    return EconomyData(time_seconds=axis, **fields)
