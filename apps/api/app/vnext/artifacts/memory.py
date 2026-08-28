"""In-memory implementation of the generic artifact store."""

from collections.abc import AsyncIterator

from .models import ArtifactRef
from .protocol import Artifact
from .store import ArtifactNotFoundError, validate_artifact_reference


class MemoryArtifactStore:
    """Store artifacts by reference id for the lifetime of the instance."""

    def __init__(self) -> None:
        self._storage: dict[str, tuple[ArtifactRef, Artifact]] = {}

    async def put(self, ref: ArtifactRef, artifact: Artifact) -> None:
        validate_artifact_reference(ref, artifact)
        self._storage[ref.id] = (ref, artifact)

    async def get(self, ref: ArtifactRef) -> Artifact:
        try:
            _, artifact = self._storage[ref.id]
        except KeyError as exc:
            raise ArtifactNotFoundError(f"artifact not found: {ref.id!r}") from exc
        validate_artifact_reference(ref, artifact)
        return artifact

    async def exists(self, ref: ArtifactRef) -> bool:
        return ref.id in self._storage

    async def iter_refs(
        self,
        artifact_types: list[str] | None = None,
    ) -> AsyncIterator[ArtifactRef]:
        """Yield stored references in deterministic id order without reading artifacts."""

        allowed_types = set(artifact_types) if artifact_types is not None else None
        for ref, _ in sorted(self._storage.values(), key=lambda stored: stored[0].id):
            if allowed_types is None or ref.artifact_type in allowed_types:
                yield ref
