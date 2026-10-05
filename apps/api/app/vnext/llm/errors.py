"""Provider-neutral errors raised by model adapters."""

from __future__ import annotations

from app.vnext.llm.diagnostics import ModelFailureDiagnostics
from app.vnext.llm.protocol import RejectedToolCallBatch


class ModelResponseDiagnosticError(RuntimeError):
    """A model response failure with optional bounded parsing evidence."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: ModelFailureDiagnostics | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class ModelToolCallBatchRejected(ModelResponseDiagnosticError):
    """A complete tool-call response was rejected before any call could run."""

    def __init__(
        self,
        *,
        batch: RejectedToolCallBatch,
        diagnostics: ModelFailureDiagnostics | None = None,
    ) -> None:
        super().__init__(
            f"model tool-call batch rejected: {batch.reason}",
            diagnostics=diagnostics,
        )
        self.batch = batch


class ModelContextWindowError(RuntimeError):
    """The model provider explicitly reported a context-window limit."""

    def __init__(self, *, provider_code: str, status_code: int | None) -> None:
        super().__init__("model provider reported a context window limit")
        self.provider_code = provider_code
        self.status_code = status_code


class ModelTransientError(RuntimeError):
    """A provider-neutral model transport error that may succeed on retry."""


__all__ = [
    "ModelContextWindowError",
    "ModelResponseDiagnosticError",
    "ModelToolCallBatchRejected",
    "ModelTransientError",
]
