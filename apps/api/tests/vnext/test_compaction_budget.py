from __future__ import annotations

import pytest

from app.vnext.agent.compaction_budget import (
    assess_compaction_request_capacity,
    resolve_compaction_output_tokens,
)
from app.vnext.agent.context_accounting import measure_request_context_bytes
from app.vnext.agent.evidence_summary_lifecycle import build_history_compaction_request
from app.vnext.llm.protocol import UserMessage


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


def test_summary_capacity_allows_exact_window_boundary_and_rejects_one_token_over() -> None:
    request = build_history_compaction_request(
        previous_summary=None,
        history_messages=[UserMessage(content="history")],
        max_output_tokens=32,
    )
    context_bytes = measure_request_context_bytes(request)
    estimated_input = (context_bytes + 1) // 2
    window = estimated_input + request.max_output_tokens + 10

    exact = assess_compaction_request_capacity(
        request,
        context_window_tokens=window,
        safety_margin_tokens=10,
        bytes_per_token=2,
    )
    over = assess_compaction_request_capacity(
        request,
        context_window_tokens=window - 1,
        safety_margin_tokens=10,
        bytes_per_token=2,
    )

    assert exact.context_bytes == context_bytes
    assert exact.estimated_input_tokens == estimated_input
    assert exact.required_tokens == window
    assert exact.fits is True
    assert over.fits is False


def test_summary_capacity_counts_old_summary_and_uses_request_output_cap() -> None:
    without_summary = build_history_compaction_request(
        previous_summary=None,
        history_messages=[UserMessage(content="history")],
        max_output_tokens=64,
    )
    with_summary = build_history_compaction_request(
        previous_summary="prior context " * 50,
        history_messages=[UserMessage(content="history")],
        max_output_tokens=48,
    )

    capacity = assess_compaction_request_capacity(
        with_summary,
        context_window_tokens=None,
        safety_margin_tokens=10,
        bytes_per_token=2,
    )

    assert capacity.context_bytes == measure_request_context_bytes(with_summary)
    assert capacity.context_bytes > measure_request_context_bytes(without_summary)
    assert capacity.max_output_tokens == 48
    assert capacity.fits is None


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "1024"])
def test_summary_capacity_rejects_invalid_estimation_configuration(value: object) -> None:
    request = build_history_compaction_request(
        previous_summary=None,
        history_messages=[UserMessage(content="history")],
        max_output_tokens=32,
    )
    with pytest.raises(ValueError):
        assess_compaction_request_capacity(
            request,
            context_window_tokens=None,
            safety_margin_tokens=10,
            bytes_per_token=value,  # type: ignore[arg-type]
        )
