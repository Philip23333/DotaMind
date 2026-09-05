"""Translate the series capability contract into one collection request."""

from __future__ import annotations

from typing import Any

from app.vnext.capabilities.esports.series import (
    LeagueSummary,
    SeriesItem,
    SeriesSearchInput,
    SeriesSearchResult,
)

from .client import PandaScoreClient


class PandaScoreSeriesAdapter:
    def __init__(self, client: PandaScoreClient) -> None:
        self.client = client

    async def search(self, query: SeriesSearchInput) -> SeriesSearchResult:
        rows = await self.client.get_list(
            "/dota2/series",
            params=self._params(query),
        )
        return SeriesSearchResult(
            items=[self._normalize(row) for row in rows],
            page=query.page,
            limit=query.limit,
        )

    @staticmethod
    def _params(query: SeriesSearchInput) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": query.page,
            "per_page": query.limit,
        }
        if query.id is not None:
            params["filter[id]"] = query.id
        if query.league_id is not None:
            params["filter[league_id]"] = query.league_id
        if query.year is not None:
            params["filter[year]"] = query.year
        if query.name is not None:
            params["search[name]"] = query.name
        if query.season is not None:
            params["search[season]"] = query.season
        return params

    @classmethod
    def _normalize(cls, row: dict[str, Any]) -> SeriesItem:
        return SeriesItem(
            id=int(row["id"]),
            name=row.get("name"),
            full_name=row.get("full_name"),
            season=row.get("season"),
            year=row.get("year"),
            begin_at=row.get("begin_at"),
            end_at=row.get("end_at"),
            league=cls._league(row.get("league")),
        )

    @staticmethod
    def _league(value: Any) -> LeagueSummary | None:
        if not isinstance(value, dict):
            return None
        entity_id = value.get("id")
        if entity_id is None:
            return None
        return LeagueSummary(id=int(entity_id), name=value.get("name"))


__all__ = ["PandaScoreSeriesAdapter"]
