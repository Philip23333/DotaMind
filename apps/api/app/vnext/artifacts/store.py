"""Artifact store contract and shared storage errors."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from .models import ArtifactRef
from .protocol import Artifact


def validate_artifact_reference(ref: ArtifactRef, artifact: Artifact) -> None:
    """Ensure stored artifact metadata agrees with its canonical reference."""

    if (
        ref.artifact_type != artifact.artifact_type
        or ref.schema_version != artifact.schema_version
    ):
        raise ArtifactTypeMismatchError(
            f"artifact {ref.id!r} does not match its reference: "
            f"expected type={ref.artifact_type!r}, "
            f"schema_version={ref.schema_version!r}; "
            f"received type={artifact.artifact_type!r}, "
            f"schema_version={artifact.schema_version!r}"
        )


@runtime_checkable
class ArtifactStore(Protocol):
    """Storage interface for typed artifacts."""

    async def put(self, ref: ArtifactRef, artifact: Artifact) -> None:
        """Store an artifact under its reference."""

    async def get(self, ref: ArtifactRef) -> Artifact:
        """Return the artifact stored under a reference."""

    async def exists(self, ref: ArtifactRef) -> bool:
        """Return whether an artifact exists under a reference."""

    async def iter_refs(
        self,
        artifact_types: list[str] | None = None,
    ) -> AsyncIterator[ArtifactRef]:
        """Yield stored references, optionally limited to artifact types."""


class ArtifactNotFoundError(LookupError):
    """Raised when a requested artifact reference has no stored value."""


class ArtifactTypeMismatchError(ValueError):
    """Raised when an artifact does not match its reference metadata."""


class ArtifactStoreUnavailableError(RuntimeError):
    """Raised when the configured artifact store cannot be reached."""
