"""Generic artifact storage contracts for the vNext foundation."""

from .game_summary import GameSummaryArtifact
from .game_summary_producer import GameSummaryArtifactProducer
from .memory import MemoryArtifactStore
from .models import ArtifactRef
from .protocol import Artifact
from .store import ArtifactNotFoundError, ArtifactStore, ArtifactTypeMismatchError

__all__ = [
    "Artifact",
    "ArtifactNotFoundError",
    "ArtifactRef",
    "ArtifactStore",
    "ArtifactTypeMismatchError",
    "GameSummaryArtifact",
    "GameSummaryArtifactProducer",
    "MemoryArtifactStore",
]
