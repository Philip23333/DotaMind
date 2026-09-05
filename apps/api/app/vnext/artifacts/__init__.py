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
from .observation import MAX_MODEL_TOOL_OBSERVATION_BYTES, build_bounded_observation
from .processor import (
    ArtifactBackedToolResultProcessor,
    ProcessedToolResult,
    ToolResultProcessor,
)
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
    "ArtifactBackedToolResultProcessor",
    "ArtifactNotFoundError",
    "ArtifactPathNotFoundError",
    "ArtifactReadResult",
    "ArtifactReadValidationError",
    "ArtifactReader",
    "ExternalizedToolResponse",
    "INLINE_TOOL_RESPONSE_MAX_BYTES",
    "InvalidArtifactRefError",
    "ManualResolver",
    "MAX_MODEL_TOOL_OBSERVATION_BYTES",
    "DOCUMENTED_MANUAL_REFS",
    "MANUAL_REFS",
    "SessionArtifactStore",
    "ProcessedToolResult",
    "ToolResponseArtifactError",
    "ToolResponseExternalizer",
    "ToolResultProcessor",
    "build_bounded_observation",
    "serialized_size",
]
