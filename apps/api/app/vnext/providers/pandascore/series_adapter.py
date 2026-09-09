"""Translate the series capability contract into one collection request."""

from __future__ import annotations

from typing import Any

from app.vnext.capabilities.esports.dtos import SeriesDTO
from app.vnext.capabilities.esports.series import (
    SeriesSearchInput,
    SeriesSearchResult,
    SeriesTeamItem,
    SeriesTeamsInput,
    SeriesTeamsResult,
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

    async def teams(self, query: SeriesTeamsInput) -> SeriesTeamsResult:
        rows = await self.client.get_list(
            f"/dota2/series/{query.series_id}/teams",
            params={"page": query.page, "per_page": query.limit},
        )
        return SeriesTeamsResult(
            items=[self._normalize_team(row) for row in rows],
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
        if query.season is not None:
            params["filter[season]"] = query.season
        if query.year is not None:
            params["filter[year]"] = query.year
        if query.winner_id is not None:
            params["filter[winner_id]"] = query.winner_id
        if query.tier is not None:
            params["filter[tier]"] = query.tier
        if query.name is not None:
            params["search[name]"] = query.name
        return params

    @classmethod
    def _normalize(cls, row: dict[str, Any]) -> SeriesDTO:
        return SeriesDTO(
            id=int(row["id"]),
            league_id=int(row["league_id"]),
            name=cls._optional_text(row.get("name")),
            full_name=cls._optional_text(row.get("full_name")),
            year=row.get("year"),
            season=cls._optional_text(row.get("season")),
            begin_at=row.get("begin_at"),
            end_at=row.get("end_at"),
            winner_id=row.get("winner_id"),
            tier=cls._optional_text(row.get("tier")),
            slug=cls._optional_text(row.get("slug")),
        )

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _normalize_team(row: dict[str, Any]) -> SeriesTeamItem:
        return SeriesTeamItem(
            id=int(row["id"]),
            name=str(row["name"]),
            acronym=row.get("acronym"),
            location=row.get("location"),
        )


__all__ = ["PandaScoreSeriesAdapter"]
