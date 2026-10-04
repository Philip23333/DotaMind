"""Pure, conservative capacity estimates for one model request."""

from __future__ import annotations

from dataclasses import dataclass

from app.vnext.llm.protocol import ModelRequest

from .context_accounting import measure_request_context_bytes
from .limits import AgentLimits
from .output_budget import OutputBudget, derive_output_budget
from .runtime_context import ContextPressure

CAPACITY_MEASUREMENT = "canonical_json_utf8_bytes_ratio_estimate"


@dataclass(frozen=True, slots=True)
class RequestCapacity:
    measurement: str
    context_bytes: int
    estimated_input_tokens: int
    expected_output_tokens: int
    actual_output_tokens: int
    remaining_output_tokens: int | None
    clipped_by_context: bool
    safety_margin_tokens: int
    context_window_tokens: int
    test_input_budget_tokens: int
    compaction_reserve_tokens: int
    production_trigger_input_tokens: int
    test_trigger_percent: int | None
    trigger_input_tokens: int
    pressure: ContextPressure


def assess_request_capacity(
    request: ModelRequest,
    limits: AgentLimits,
    *,
    output_budget: OutputBudget | None = None,
) -> RequestCapacity | None:
    """Estimate request pressure without changing or executing anything."""

    window = limits.context_window_tokens
    if window is None:
        return None

    budget = output_budget or derive_output_budget(request, limits)
    context_bytes = measure_request_context_bytes(request)
    estimated_input_tokens = budget.estimated_input_tokens
    test_input_budget_tokens = max(
        0,
        window - budget.expected_output_tokens - limits.context_safety_margin_tokens,
    )
    production_trigger_input_tokens = window - limits.compaction_reserve_tokens + 1
    test_trigger_input_tokens = None
    if limits.context_compaction_test_trigger_percent is not None:
        percent = limits.context_compaction_test_trigger_percent
        test_trigger_input_tokens = (test_input_budget_tokens * percent + 99) // 100
    trigger_input_tokens = (
        min(production_trigger_input_tokens, test_trigger_input_tokens)
        if test_trigger_input_tokens is not None
        else production_trigger_input_tokens
    )

    fits = (
        budget.actual_output_tokens > 0
        and estimated_input_tokens
        + budget.actual_output_tokens
        + limits.context_safety_margin_tokens
        <= window
    )
    if not fits:
        pressure = ContextPressure.CRITICAL
    elif estimated_input_tokens >= trigger_input_tokens:
        pressure = ContextPressure.HIGH
    else:
        pressure = ContextPressure.NORMAL

    return RequestCapacity(
        measurement=CAPACITY_MEASUREMENT,
        context_bytes=context_bytes,
        estimated_input_tokens=estimated_input_tokens,
        expected_output_tokens=budget.expected_output_tokens,
        actual_output_tokens=budget.actual_output_tokens,
        remaining_output_tokens=budget.remaining_output_tokens,
        clipped_by_context=budget.clipped_by_context,
        safety_margin_tokens=limits.context_safety_margin_tokens,
        context_window_tokens=window,
        test_input_budget_tokens=test_input_budget_tokens,
        compaction_reserve_tokens=limits.compaction_reserve_tokens,
        production_trigger_input_tokens=production_trigger_input_tokens,
        test_trigger_percent=limits.context_compaction_test_trigger_percent,
        trigger_input_tokens=trigger_input_tokens,
        pressure=pressure,
    )


__all__ = ["CAPACITY_MEASUREMENT", "RequestCapacity", "assess_request_capacity"]
