"""STRATZ bracket enum translation.

STRATZ exposes two rank enums:
- RankBracketBasicEnum (HERALD_GUARDIAN / CRUSADER_ARCHON / LEGEND_ANCIENT /
  DIVINE_IMMORTAL / UNCALIBRATED + FILTERED/ALL) — used by week-grain tools
  (laneOutcome / heroVsHeroMatchup / stats).
- RankBracket (UNCALIBRATED / HERALD / GUARDIAN / CRUSADER / ARCHON / LEGEND /
  ANCIENT / DIVINE / IMMORTAL) — used by day-grain winDay.

winDay only accepts the full RankBracket enum, so a basic bracket set on
plan.context.bracket must be expanded before calling winDay. Other tools keep
using basic directly. See docs/design/STRATZ工具审计与重构输入.md §4 P1-4.
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
