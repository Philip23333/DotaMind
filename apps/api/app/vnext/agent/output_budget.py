"""Pure output-budget calculation for ordinary model requests."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.vnext.llm.protocol import ModelRequest

from .context_accounting import measure_request_context_bytes
from .limits import AgentLimits


@dataclass(frozen=True, slots=True)
class OutputBudget:
    expected_output_tokens: int
    actual_output_tokens: int
    estimated_input_tokens: int
    remaining_output_tokens: int | None
    clipped_by_context: bool

    def to_dict(self) -> dict[str, int | bool | None]:
        return asdict(self)


def derive_output_budget(request: ModelRequest, limits: AgentLimits) -> OutputBudget:
    """Resolve a finite output cap, clipped to this request's remaining window."""

    expected = resolve_expected_output_tokens(limits)
    context_bytes = measure_request_context_bytes(request)
    bytes_per_token = limits.context_estimate_bytes_per_token
    estimated_input = (context_bytes + bytes_per_token - 1) // bytes_per_token
    window = limits.context_window_tokens
    if window is None:
        return OutputBudget(
            expected_output_tokens=expected,
            actual_output_tokens=expected,
            estimated_input_tokens=estimated_input,
            remaining_output_tokens=None,
            clipped_by_context=False,
        )

    remaining = max(0, window - estimated_input - limits.context_safety_margin_tokens)
    actual = min(expected, remaining)
    return OutputBudget(
        expected_output_tokens=expected,
        actual_output_tokens=actual,
        estimated_input_tokens=estimated_input,
        remaining_output_tokens=remaining,
        clipped_by_context=actual < expected,
    )


def resolve_expected_output_tokens(limits: AgentLimits) -> int:
    """Return the model/application cap before request-specific clipping."""

    model_cap = limits.model_max_output_tokens
    application_cap = limits.application_max_output_tokens
    if model_cap is None and application_cap is None:
        raise ValueError(
            "configure DOTAMIND_MODEL_MAX_OUTPUT_TOKENS or "
            "DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS before model calls"
        )
    if model_cap is None:
        expected = application_cap
    elif application_cap is None:
        expected = model_cap
    else:
        expected = min(model_cap, application_cap)
    assert expected is not None
    return expected


__all__ = ["OutputBudget", "derive_output_budget", "resolve_expected_output_tokens"]
