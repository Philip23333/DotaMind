"""Generic artifact storage contracts for the vNext foundation."""

from .game_summary import GameSummaryArtifact
from .game_summary_producer import GameSummaryArtifactProducer
from .game_summary_v4 import GameSummaryArtifactV4
from .memory import MemoryArtifactStore
from .models import ArtifactRef, game_summary_artifact_ref
from .protocol import Artifact
from .retrieval import (
    ArtifactPathNotFoundError,
    ArtifactReader,
    ArtifactReadResult,
    ArtifactReadValidationError,
    ArtifactSearcher,
    ArtifactSearchResult,
)
from .store import ArtifactNotFoundError, ArtifactStore, ArtifactTypeMismatchError

__all__ = [
    "Artifact",
    "ArtifactNotFoundError",
    "ArtifactRef",
    "ArtifactPathNotFoundError",
    "ArtifactReadResult",
    "ArtifactReadValidationError",
    "ArtifactReader",
    "ArtifactSearchResult",
    "ArtifactSearcher",
    "ArtifactStore",
    "ArtifactTypeMismatchError",
    "GameSummaryArtifact",
    "GameSummaryArtifactV4",
    "GameSummaryArtifactProducer",
    "MemoryArtifactStore",
    "game_summary_artifact_ref",
]
