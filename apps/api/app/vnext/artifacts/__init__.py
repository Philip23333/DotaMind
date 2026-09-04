"""Session-local, bounded access to externalized tool responses."""

from .externalize import (
    INLINE_TOOL_RESPONSE_MAX_BYTES,
    ExternalizedToolResponse,
    ToolResponseArtifactError,
    ToolResponseExternalizer,
    serialized_size,
)
from .grep import ArtifactGrepMatch, ArtifactGrepper, ArtifactGrepResult
from .manuals import DOCUMENTED_MANUAL_REFS, MANUAL_REFS, ManualResolver
from .retrieval import (
    ArtifactPathNotFoundError,
    ArtifactReader,
    ArtifactReadResult,
    ArtifactReadValidationError,
)
from .store import ArtifactNotFoundError, InvalidArtifactRefError, SessionArtifactStore

__all__ = [
    "ArtifactGrepMatch",
    "ArtifactGrepResult",
    "ArtifactGrepper",
    "ArtifactNotFoundError",
    "ArtifactPathNotFoundError",
    "ArtifactReadResult",
    "ArtifactReadValidationError",
    "ArtifactReader",
    "ExternalizedToolResponse",
    "INLINE_TOOL_RESPONSE_MAX_BYTES",
    "InvalidArtifactRefError",
    "ManualResolver",
    "DOCUMENTED_MANUAL_REFS",
    "MANUAL_REFS",
    "SessionArtifactStore",
    "ToolResponseArtifactError",
    "ToolResponseExternalizer",
    "serialized_size",
]
