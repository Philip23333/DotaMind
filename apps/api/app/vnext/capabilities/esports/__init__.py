"""Source-backed esports discovery capability."""

from .models import (
    EsportsKind,
    EsportsSearchProvider,
    EsportsSearchRequest,
    EsportsSearchResult,
    EsportsSearchWarning,
    ProviderEntity,
    ProviderSearchBatch,
    SourceRecord,
    TimeScope,
)
from .service import EsportsSearchService

__all__ = [
    "EsportsKind",
    "EsportsSearchProvider",
    "EsportsSearchRequest",
    "EsportsSearchResult",
    "EsportsSearchWarning",
    "EsportsSearchService",
    "ProviderEntity",
    "ProviderSearchBatch",
    "SourceRecord",
    "TimeScope",
]
