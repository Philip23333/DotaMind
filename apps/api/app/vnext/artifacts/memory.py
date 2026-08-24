"""In-memory implementation of the generic artifact store."""

from .models import ArtifactRef
from .protocol import Artifact
from .store import ArtifactNotFoundError, ArtifactTypeMismatchError


class MemoryArtifactStore:
    """Store artifacts by reference id for the lifetime of the instance."""

    def __init__(self) -> None:
        self._storage: dict[str, Artifact] = {}

    def put(self, ref: ArtifactRef, artifact: Artifact) -> None:
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

        self._storage[ref.id] = artifact

    def get(self, ref: ArtifactRef) -> Artifact:
        try:
            return self._storage[ref.id]
        except KeyError as exc:
            raise ArtifactNotFoundError(f"artifact not found: {ref.id!r}") from exc

    def exists(self, ref: ArtifactRef) -> bool:
        return ref.id in self._storage
