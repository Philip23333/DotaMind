"""In-memory implementation of the generic artifact store."""

from .models import ArtifactRef
from .protocol import Artifact
from .store import ArtifactNotFoundError, validate_artifact_reference


class MemoryArtifactStore:
    """Store artifacts by reference id for the lifetime of the instance."""

    def __init__(self) -> None:
        self._storage: dict[str, Artifact] = {}

    async def put(self, ref: ArtifactRef, artifact: Artifact) -> None:
        validate_artifact_reference(ref, artifact)
        self._storage[ref.id] = artifact

    async def get(self, ref: ArtifactRef) -> Artifact:
        try:
            artifact = self._storage[ref.id]
        except KeyError as exc:
            raise ArtifactNotFoundError(f"artifact not found: {ref.id!r}") from exc
        validate_artifact_reference(ref, artifact)
        return artifact

    async def exists(self, ref: ArtifactRef) -> bool:
        return ref.id in self._storage
