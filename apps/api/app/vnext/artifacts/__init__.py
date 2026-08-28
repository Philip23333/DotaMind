"""Generic artifact storage contracts for the vNext foundation."""

from .game_summary import GameSummaryArtifact
from .game_summary_producer import GameSummaryArtifactProducer
from .game_summary_v4 import GameSummaryArtifactV4
from .grep import ArtifactGrepMatch, ArtifactGrepper, ArtifactGrepResult
from .memory import MemoryArtifactStore
from .models import ArtifactRef, game_summary_artifact_ref
from .protocol import Artifact
from .redis import RedisArtifactStore
from .retrieval import (
    ArtifactPathNotFoundError,
    ArtifactReader,
    ArtifactReadResult,
    ArtifactReadValidationError,
    ArtifactSearcher,
    ArtifactSearchResult,
)
from .store import (
    ArtifactNotFoundError,
    ArtifactStore,
    ArtifactStoreUnavailableError,
    ArtifactTypeMismatchError,
)

__all__ = [
    "Artifact",
    "ArtifactNotFoundError",
    "ArtifactRef",
    "ArtifactGrepMatch",
    "ArtifactGrepResult",
    "ArtifactGrepper",
    "ArtifactPathNotFoundError",
    "ArtifactReadResult",
    "ArtifactReadValidationError",
    "ArtifactReader",
    "ArtifactSearchResult",
    "ArtifactSearcher",
    "ArtifactStore",
    "ArtifactStoreUnavailableError",
    "ArtifactTypeMismatchError",
    "GameSummaryArtifact",
    "GameSummaryArtifactV4",
    "GameSummaryArtifactProducer",
    "MemoryArtifactStore",
    "RedisArtifactStore",
    "game_summary_artifact_ref",
]
