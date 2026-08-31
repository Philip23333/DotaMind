"""Generic artifact storage contracts for the vNext foundation."""

from .game_detail import GameDetailArtifact, game_detail_artifact_ref
from .game_summary import GameSummaryArtifact
from .game_summary_producer import GameSummaryArtifactProducer
from .game_summary_v4 import GameSummaryArtifactV4
from .game_summary_v5 import GameSummaryArtifactV5
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
from .scope import (
    ArtifactScopeRef,
    ArtifactScopeStore,
    MemoryArtifactScopeStore,
    RedisArtifactScopeStore,
)
from .source_document import (
    SourceDocumentArtifact,
    bounded_source_observation,
    source_document_artifact_ref,
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
    "ArtifactScopeRef",
    "ArtifactScopeStore",
    "ArtifactStore",
    "ArtifactStoreUnavailableError",
    "ArtifactTypeMismatchError",
    "GameSummaryArtifact",
    "GameDetailArtifact",
    "GameSummaryArtifactV4",
    "GameSummaryArtifactV5",
    "GameSummaryArtifactProducer",
    "MemoryArtifactStore",
    "MemoryArtifactScopeStore",
    "RedisArtifactStore",
    "RedisArtifactScopeStore",
    "SourceDocumentArtifact",
    "bounded_source_observation",
    "game_summary_artifact_ref",
    "game_detail_artifact_ref",
    "source_document_artifact_ref",
]
