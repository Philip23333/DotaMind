import pytest

from app.integrations.stratz.brackets import basic_to_full


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
