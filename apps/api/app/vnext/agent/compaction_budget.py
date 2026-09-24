"""Pure helpers for deriving compaction response budgets."""

from typing import Literal


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


__all__ = ["resolve_compaction_output_tokens"]
