"""STRATZ bracket enum translation.

STRATZ exposes two rank enums:
- RankBracketBasicEnum (HERALD_GUARDIAN / CRUSADER_ARCHON / LEGEND_ANCIENT /
  DIVINE_IMMORTAL / UNCALIBRATED + FILTERED/ALL) — used by week-grain tools
  (laneOutcome / heroVsHeroMatchup / stats).
- RankBracket (UNCALIBRATED / HERALD / GUARDIAN / CRUSADER / ARCHON / LEGEND /
  ANCIENT / DIVINE / IMMORTAL) — used by day-grain winDay.

winDay only accepts the full RankBracket enum, so a basic bracket set on
plan.context.bracket must be expanded before calling winDay. Other tools keep
using basic directly. See docs/design/tools/STRATZ工具审计与重构输入.md §4 P1-4.
"""

_BASIC_TO_FULL: dict[str, list[str]] = {
    "UNCALIBRATED": ["UNCALIBRATED"],
    "HERALD_GUARDIAN": ["HERALD", "GUARDIAN"],
    "CRUSADER_ARCHON": ["CRUSADER", "ARCHON"],
    "LEGEND_ANCIENT": ["LEGEND", "ANCIENT"],
    "DIVINE_IMMORTAL": ["DIVINE", "IMMORTAL"],
}


def basic_to_full(basic: list[str] | None) -> list[str] | None:
    """Expand a RankBracketBasicEnum list to RankBracket values for winDay.

    None / [] -> None (no bracketIds filter; STRATZ returns all ranks).
    Unknown basic values raise ValueError (fail loud; do not silently drop).
    """
    if not basic:
        return None
    expanded: list[str] = []
    for value in basic:
        mapping = _BASIC_TO_FULL.get(value)
        if mapping is None:
            raise ValueError(
                f"unknown RankBracketBasicEnum value: {value!r}; "
                f"expected one of {sorted(_BASIC_TO_FULL)}"
            )
        expanded.extend(mapping)
    return expanded


# bracketIds (0-8) for PlayerMatchesRequest. Distinct value-space from the
# rankIds (0-80) needed by PlayerHeroPerformanceMatchesRequestType — see
# basic_to_rank_ids below. Do NOT mix these two mappings.
# Ordinal = bracket int (UNCALIBRATED=0 ... IMMORTAL=8), the standard STRATZ
# encoding; enum descriptions are empty so this is convention, low-risk.
_BASIC_TO_BRACKET_IDS: dict[str, list[int]] = {
    "UNCALIBRATED": [0],
    "HERALD_GUARDIAN": [1, 2],
    "CRUSADER_ARCHON": [3, 4],
    "LEGEND_ANCIENT": [5, 6],
    "DIVINE_IMMORTAL": [7, 8],
}


def basic_to_bracket_ids(basic: list[str] | None) -> list[int] | None:
    """Map RankBracketBasicEnum -> bracketIds ints (0-8) for PlayerMatchesRequest.

    None / [] -> None (no bracket filter). Unknown basic values, or full-enum
    values that do not belong to the basic enum (DIVINE/IMMORTAL/FILTERED/ALL),
    raise ValueError (fail loud; do not silently drop).
    """
    if not basic:
        return None
    ids: list[int] = []
    for value in basic:
        mapping = _BASIC_TO_BRACKET_IDS.get(value)
        if mapping is None:
            raise ValueError(
                f"unknown RankBracketBasicEnum value: {value!r}; "
                f"expected one of {sorted(_BASIC_TO_BRACKET_IDS)}"
            )
        ids.extend(mapping)
    return ids


# rankIds (0-80) for PlayerHeroPerformanceMatchesRequestType. LIVE-LOCKED
# 2026-07-08 (probe on player 853634884, seasonRank=80): encoding is
# bracket(1-8)*10 + star(0-4); Immortal collapses to {80}; the *5-*9 slots are
# unused gaps (probed empty at 25/65/75/76/79). See inventory §basic_to_rank_ids.
# Distinct value-space from bracketIds (0-8) above — do NOT mix the two mappings.
# Bracket ordinals (Herald=1 ... Immortal=8); UNCALIBRATED is handled inline (=0).
_BASIC_TO_RANK_BRACKETS: dict[str, list[int]] = {
    "HERALD_GUARDIAN": [1, 2],
    "CRUSADER_ARCHON": [3, 4],
    "LEGEND_ANCIENT": [5, 6],
    "DIVINE_IMMORTAL": [7, 8],
}


def _rank_ids_for_bracket(bracket: int) -> list[int]:
    """bracket(1-8)*10 + star(0-4); Immortal(8) collapses to {80} (no stars)."""
    if bracket == 8:
        return [80]
    return [bracket * 10 + star for star in range(5)]  # star 0..4


def basic_to_rank_ids(basic: list[str] | None) -> list[int] | None:
    """Map RankBracketBasicEnum -> rankIds ints (0-80) for
    PlayerHeroPerformanceMatchesRequestType (heroesPerformance; that endpoint
    has no bracketIds, only rankIds).

    None / [] -> None (no rank filter; STRATZ returns all ranks). UNCALIBRATED
    -> [0]. Unknown basic values, or full-enum values that do not belong to the
    basic enum (DIVINE/IMMORTAL/FILTERED/ALL), raise ValueError (fail loud).

    Encoding (LIVE-LOCKED): bracket(1-8)*10 + star(0-4); Immortal={80}.
    Examples: HERALD_GUARDIAN->[10..14,20..24]; DIVINE_IMMORTAL->[70..74,80].
    """
    if not basic:
        return None
    ids: list[int] = []
    for value in basic:
        if value == "UNCALIBRATED":
            ids.append(0)
            continue
        brackets = _BASIC_TO_RANK_BRACKETS.get(value)
        if brackets is None:
            raise ValueError(
                f"unknown RankBracketBasicEnum value: {value!r}; "
                f"expected one of {sorted(_BASIC_TO_RANK_BRACKETS) + ['UNCALIBRATED']}"
            )
        for bracket in brackets:
            ids.extend(_rank_ids_for_bracket(bracket))
    return ids
