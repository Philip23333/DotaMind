"""Pure helpers for deriving compaction response budgets."""

from dataclasses import dataclass
from typing import Literal

from app.vnext.agent.context_accounting import measure_request_context_bytes
from app.vnext.llm.protocol import ModelRequest


@dataclass(frozen=True, slots=True)
class CompactionRequestCapacity:
    measurement: str
    context_bytes: int
    estimated_input_tokens: int
    context_window_tokens: int | None
    max_output_tokens: int
    safety_margin_tokens: int
    required_tokens: int
    fits: bool | None


def assess_compaction_request_capacity(
    request: ModelRequest,
    *,
    context_window_tokens: int | None,
    safety_margin_tokens: int,
    bytes_per_token: int,
) -> CompactionRequestCapacity:
    """Measure a fully constructed summary request against a configured window."""

    if context_window_tokens is not None and (
        type(context_window_tokens) is not int or context_window_tokens <= 0
    ):
        raise ValueError("context_window_tokens must be a positive integer or None")
    if type(safety_margin_tokens) is not int or safety_margin_tokens <= 0:
        raise ValueError("safety_margin_tokens must be a positive integer")
    if type(bytes_per_token) is not int or bytes_per_token <= 0:
        raise ValueError("bytes_per_token must be a positive integer")
    if type(request.max_output_tokens) is not int or request.max_output_tokens <= 0:
        raise ValueError("request must have a positive max_output_tokens")

    context_bytes = measure_request_context_bytes(request)
    estimated_input_tokens = (context_bytes + bytes_per_token - 1) // bytes_per_token
    required_tokens = estimated_input_tokens + request.max_output_tokens + safety_margin_tokens
    fits = (
        required_tokens <= context_window_tokens if context_window_tokens is not None else None
    )
    return CompactionRequestCapacity(
        measurement="canonical_json_utf8_bytes_ratio_estimate",
        context_bytes=context_bytes,
        estimated_input_tokens=estimated_input_tokens,
        context_window_tokens=context_window_tokens,
        max_output_tokens=request.max_output_tokens,
        safety_margin_tokens=safety_margin_tokens,
        required_tokens=required_tokens,
        fits=fits,
    )


def resolve_compaction_output_tokens(
    *,
    kind: Literal["history", "turn_prefix"],
    reserve_tokens: int,
    model_max_output_tokens: int | None,
) -> int:
    """Resolve a compaction output allowance from its reserved token budget."""

    if type(kind) is not str:
        raise TypeError("kind must be a string")
    if kind not in {"history", "turn_prefix"}:
        raise ValueError("kind must be 'history' or 'turn_prefix'")
    if type(reserve_tokens) is not int:
        raise TypeError("reserve_tokens must be an integer")
    if reserve_tokens < 2:
        raise ValueError("reserve_tokens must be at least 2")
    if model_max_output_tokens is not None:
        if type(model_max_output_tokens) is not int:
            raise TypeError("model_max_output_tokens must be an integer or None")
        if model_max_output_tokens <= 0:
            raise ValueError("model_max_output_tokens must be positive")

    if kind == "history":
        derived_tokens = reserve_tokens * 4 // 5
    else:
        derived_tokens = reserve_tokens // 2

    if model_max_output_tokens is None:
        return derived_tokens
    return min(derived_tokens, model_max_output_tokens)


__all__ = [
    "CompactionRequestCapacity",
    "assess_compaction_request_capacity",
    "resolve_compaction_output_tokens",
]
