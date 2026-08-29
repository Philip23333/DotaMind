"""Thin service boundary for the first esports-search implementation."""

from app.vnext.domain.source import SourceLocator

from .models import EsportsSearchResult
from .pandascore import PandaScoreEsportsSearch, TimeScope


class EsportsSearchService:
    """Expose broad source-backed esports search without provider-named tools."""

    def __init__(self, provider: PandaScoreEsportsSearch) -> None:
        self._provider = provider

    async def search(
        self,
        *,
        query: str | None = None,
        within: SourceLocator | None = None,
        time_scope: TimeScope = "all",
        limit: int = 10,
    ) -> EsportsSearchResult:
        return await self._provider.search(
            query=query,
            within=within,
            time_scope=time_scope,
            limit=limit,
        )


__all__ = ["EsportsSearchService"]
