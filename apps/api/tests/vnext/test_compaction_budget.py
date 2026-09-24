from __future__ import annotations

import pytest

from app.vnext.agent.compaction_budget import resolve_compaction_output_tokens


@pytest.mark.parametrize(
    ("reserve_tokens", "model_max_output_tokens", "expected_history", "expected_prefix"),
    [
        (16_384, None, 13_107, 8_192),
        (16_384, 8_192, 8_192, 8_192),
        (16_384, 4_096, 4_096, 4_096),
        (5, None, 4, 2),
    ],
)
def test_compaction_output_budgets_follow_kind_ratio_and_model_cap(
    reserve_tokens: int,
    model_max_output_tokens: int | None,
    expected_history: int,
    expected_prefix: int,
) -> None:
    assert (
        resolve_compaction_output_tokens(
            kind="history",
            reserve_tokens=reserve_tokens,
            model_max_output_tokens=model_max_output_tokens,
        )
        == expected_history
    )
    assert (
        resolve_compaction_output_tokens(
            kind="turn_prefix",
            reserve_tokens=reserve_tokens,
            model_max_output_tokens=model_max_output_tokens,
        )
        == expected_prefix
    )


@pytest.mark.parametrize("kind", ["unknown", "", 1, True, None])
def test_unknown_or_invalid_compaction_kind_is_rejected(kind: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        resolve_compaction_output_tokens(
            kind=kind,  # type: ignore[arg-type]
            reserve_tokens=16_384,
            model_max_output_tokens=None,
        )


@pytest.mark.parametrize("reserve_tokens", [True, False, 1.5, "16384", None])
def test_reserve_tokens_must_be_a_strict_integer(reserve_tokens: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        resolve_compaction_output_tokens(
            kind="history",
            reserve_tokens=reserve_tokens,  # type: ignore[arg-type]
            model_max_output_tokens=None,
        )


@pytest.mark.parametrize("reserve_tokens", [0, 1, -1])
def test_reserve_tokens_must_leave_each_derived_budget_positive(
    reserve_tokens: int,
) -> None:
    with pytest.raises(ValueError, match="at least 2"):
        resolve_compaction_output_tokens(
            kind="history",
            reserve_tokens=reserve_tokens,
            model_max_output_tokens=None,
        )


@pytest.mark.parametrize("model_max_output_tokens", [True, False, 1.5, "4096", 0, -1])
def test_configured_model_output_limit_must_be_a_positive_strict_integer(
    model_max_output_tokens: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        resolve_compaction_output_tokens(
            kind="history",
            reserve_tokens=16_384,
            model_max_output_tokens=model_max_output_tokens,  # type: ignore[arg-type]
        )
