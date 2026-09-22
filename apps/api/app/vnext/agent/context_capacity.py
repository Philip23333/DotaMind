"""Pure, conservative capacity estimates for one model request."""

from __future__ import annotations

from dataclasses import dataclass

from app.vnext.llm.protocol import ModelRequest

from .context_accounting import measure_request_context_bytes
from .limits import AgentLimits
from .runtime_context import ContextPressure

CAPACITY_MEASUREMENT = "canonical_json_utf8_bytes_ratio_estimate"


@dataclass(frozen=True)
class RequestCapacity:
    measurement: str
    context_bytes: int
    estimated_input_tokens: int
    reserved_output_tokens: int
    safety_margin_tokens: int
    context_window_tokens: int
    available_input_tokens: int
    trigger_input_tokens: int
    pressure: ContextPressure


def assess_request_capacity(
    request: ModelRequest,
    limits: AgentLimits,
) -> RequestCapacity | None:
    """Estimate request pressure without changing or executing anything."""

    window = limits.context_window_tokens
    if window is None:
        return None

    context_bytes = measure_request_context_bytes(request)
    bytes_per_token = limits.context_estimate_bytes_per_token
    estimated_input_tokens = (context_bytes + bytes_per_token - 1) // bytes_per_token
    reserved_output_tokens = (
        request.max_output_tokens
        if request.max_output_tokens is not None
        else limits.context_output_reserve_tokens
    )
    available_input_tokens = max(
        0,
        window - reserved_output_tokens - limits.context_safety_margin_tokens,
    )
    trigger_input_tokens = (
        available_input_tokens * limits.context_compaction_trigger_percent + 99
    ) // 100
    if (
        available_input_tokens == 0
        or estimated_input_tokens >= available_input_tokens
    ):
        pressure = ContextPressure.CRITICAL
    elif estimated_input_tokens >= trigger_input_tokens:
        pressure = ContextPressure.HIGH
    else:
        pressure = ContextPressure.NORMAL
    return RequestCapacity(
        measurement=CAPACITY_MEASUREMENT,
        context_bytes=context_bytes,
        estimated_input_tokens=estimated_input_tokens,
        reserved_output_tokens=reserved_output_tokens,
        safety_margin_tokens=limits.context_safety_margin_tokens,
        context_window_tokens=window,
        available_input_tokens=available_input_tokens,
        trigger_input_tokens=trigger_input_tokens,
        pressure=pressure,
    )


__all__ = [
    "CAPACITY_MEASUREMENT",
    "RequestCapacity",
    "assess_request_capacity",
]
