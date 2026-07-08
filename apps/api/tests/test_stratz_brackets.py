import pytest

from app.integrations.stratz.brackets import (
    basic_to_bracket_ids,
    basic_to_full,
    basic_to_rank_ids,
)


def test_basic_to_full_none_returns_none() -> None:
    assert basic_to_full(None) is None


def test_basic_to_full_empty_returns_none() -> None:
    assert basic_to_full([]) is None


def test_basic_to_full_divine_immortal() -> None:
    assert basic_to_full(["DIVINE_IMMORTAL"]) == ["DIVINE", "IMMORTAL"]


def test_basic_to_full_multiple() -> None:
    assert basic_to_full(["HERALD_GUARDIAN", "LEGEND_ANCIENT"]) == [
        "HERALD", "GUARDIAN", "LEGEND", "ANCIENT"
    ]


def test_basic_to_full_uncalibrated() -> None:
    assert basic_to_full(["UNCALIBRATED"]) == ["UNCALIBRATED"]


def test_basic_to_full_unknown_raises() -> None:
    with pytest.raises(ValueError):
        basic_to_full(["UNKNOWN_TIER"])


# --- basic_to_bracket_ids (0-8 space, PlayerMatchesRequest) ---


def test_bracket_ids_none_returns_none() -> None:
    assert basic_to_bracket_ids(None) is None


def test_bracket_ids_empty_returns_none() -> None:
    assert basic_to_bracket_ids([]) is None


def test_bracket_ids_divine_immortal() -> None:
    assert basic_to_bracket_ids(["DIVINE_IMMORTAL"]) == [7, 8]


def test_bracket_ids_uncalibrated() -> None:
    assert basic_to_bracket_ids(["UNCALIBRATED"]) == [0]


def test_bracket_ids_full_enum_value_rejected() -> None:
    # DIVINE/IMMORTAL belong to the full RankBracket enum, NOT the basic enum;
    # handing them to the basic helper must fail loud.
    with pytest.raises(ValueError):
        basic_to_bracket_ids(["DIVINE"])


def test_bracket_ids_filtered_all_rejected() -> None:
    with pytest.raises(ValueError):
        basic_to_bracket_ids(["FILTERED"])
    with pytest.raises(ValueError):
        basic_to_bracket_ids(["ALL"])


# --- basic_to_rank_ids (0-80 space, PlayerHeroPerformanceMatchesRequest) ---
# LIVE-LOCKED 2026-07-08: bracket(1-8)*10 + star(0-4); Immortal={80}.


def test_rank_ids_none_returns_none() -> None:
    assert basic_to_rank_ids(None) is None


def test_rank_ids_empty_returns_none() -> None:
    assert basic_to_rank_ids([]) is None


def test_rank_ids_herald_guardian() -> None:
    assert basic_to_rank_ids(["HERALD_GUARDIAN"]) == [10, 11, 12, 13, 14, 20, 21, 22, 23, 24]


def test_rank_ids_divine_immortal_boundary() -> None:
    # Divine 4 stars = 74 (user-verified); Immortal = 80; the *5-*9 slots are
    # gaps (probed empty). Divine ends at 74, NOT 75.
    assert basic_to_rank_ids(["DIVINE_IMMORTAL"]) == [70, 71, 72, 73, 74, 80]


def test_rank_ids_uncalibrated() -> None:
    assert basic_to_rank_ids(["UNCALIBRATED"]) == [0]


def test_rank_ids_multiple_pairs() -> None:
    assert basic_to_rank_ids(["CRUSADER_ARCHON", "LEGEND_ANCIENT"]) == [
        30, 31, 32, 33, 34, 40, 41, 42, 43, 44,
        50, 51, 52, 53, 54, 60, 61, 62, 63, 64,
    ]


def test_rank_ids_full_enum_value_rejected() -> None:
    with pytest.raises(ValueError):
        basic_to_rank_ids(["DIVINE"])
    with pytest.raises(ValueError):
        basic_to_rank_ids(["IMMORTAL"])


def test_rank_ids_filtered_all_rejected() -> None:
    with pytest.raises(ValueError):
        basic_to_rank_ids(["FILTERED"])
    with pytest.raises(ValueError):
        basic_to_rank_ids(["ALL"])


def test_rank_ids_unknown_raises() -> None:
    with pytest.raises(ValueError):
        basic_to_rank_ids(["UNKNOWN_TIER"])
