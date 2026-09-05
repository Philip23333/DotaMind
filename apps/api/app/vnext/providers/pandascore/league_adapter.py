"""Translate the league capability contract into one collection request."""

from __future__ import annotations

from typing import Any

from app.vnext.capabilities.esports.league import (
    LeagueItem,
    LeagueSearchInput,
    LeagueSearchResult,
)

from .client import PandaScoreClient


class PandaScoreLeagueAdapter:
    def __init__(self, client: PandaScoreClient) -> None:
        self.client = client

    async def search(self, query: LeagueSearchInput) -> LeagueSearchResult:
        rows = await self.client.get_list(
            "/dota2/leagues",
            params=self._params(query),
        )
        return LeagueSearchResult(
            items=[self._normalize(row) for row in rows],
            page=query.page,
            limit=query.limit,
        )

    @staticmethod
    def _params(query: LeagueSearchInput) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": query.page,
            "per_page": query.limit,
        }
        if query.id is not None:
            params["filter[id]"] = query.id
        if query.name is not None:
            params["search[name]"] = query.name
        return params

    @staticmethod
    def _normalize(row: dict[str, Any]) -> LeagueItem:
        return LeagueItem(
            id=int(row["id"]),
            name=str(row["name"]),
        )


__all__ = ["PandaScoreLeagueAdapter"]
