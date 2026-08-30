"""Sanitized failures that have explicit esports-search tool semantics."""

from __future__ import annotations

from typing import Any


class EsportsSearchError(RuntimeError):
    """Base class for expected capability failures safe to expose to the model."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class EsportsInvalidArgumentsError(EsportsSearchError):
    """A cross-field esports request constraint was violated."""


class EsportsProviderError(EsportsSearchError):
    """A configured source could not satisfy a valid esports request."""

    def __init__(self, *, source: str, kind: str) -> None:
        super().__init__(
            "esports provider failed",
            details={"source": source, "kind": kind},
        )


class ArtifactExternalizationError(EsportsSearchError):
    """A final source document could not be persisted as an Artifact."""

    def __init__(self, *, source: str, kind: str) -> None:
        super().__init__(
            "esports result artifact could not be stored",
            details={"source": source, "kind": kind},
        )


__all__ = [
    "ArtifactExternalizationError",
    "EsportsInvalidArgumentsError",
    "EsportsProviderError",
    "EsportsSearchError",
]
