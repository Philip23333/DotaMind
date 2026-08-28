"""Artifact store contract and shared storage errors."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import ArtifactRef
from .protocol import Artifact


@runtime_checkable
class ArtifactStore(Protocol):
    """Storage interface for typed artifacts."""

    async def put(self, ref: ArtifactRef, artifact: Artifact) -> None:
        """Store an artifact under its reference."""

    async def get(self, ref: ArtifactRef) -> Artifact:
        """Return the artifact stored under a reference."""

    async def exists(self, ref: ArtifactRef) -> bool:
        """Return whether an artifact exists under a reference."""


class ArtifactNotFoundError(LookupError):
    """Raised when a requested artifact reference has no stored value."""


class ArtifactTypeMismatchError(ValueError):
    """Raised when an artifact does not match its reference metadata."""


class ArtifactStoreUnavailableError(RuntimeError):
    """Raised when the configured artifact store cannot be reached."""
