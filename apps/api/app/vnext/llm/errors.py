"""Provider-neutral errors raised by model adapters."""

from __future__ import annotations


class ModelContextWindowError(RuntimeError):
    """The model provider explicitly reported a context-window limit."""

    def __init__(self, *, provider_code: str, status_code: int | None) -> None:
        super().__init__("model provider reported a context window limit")
        self.provider_code = provider_code
        self.status_code = status_code


__all__ = ["ModelContextWindowError"]
