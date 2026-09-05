"""Translate the team capability contract into one collection request."""

from __future__ import annotations

from typing import Any

from app.vnext.capabilities.esports.team import (
    TeamItem,
    TeamSearchInput,
    TeamSearchResult,
)

from .client import PandaScoreClient


class PandaScoreTeamAdapter:
    def __init__(self, client: PandaScoreClient) -> None:
        self.client = client

    async def search(self, query: TeamSearchInput) -> TeamSearchResult:
        rows = await self.client.get_list(
            "/dota2/teams",
            params=self._params(query),
        )
        return TeamSearchResult(
            items=[self._normalize(row) for row in rows],
            page=query.page,
            limit=query.limit,
        )

    @staticmethod
    def _params(query: TeamSearchInput) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": query.page,
            "per_page": query.limit,
        }
        if query.id is not None:
            params["filter[id]"] = query.id
        if query.name is not None:
            params["search[name]"] = query.name
        if query.acronym is not None:
            params["search[acronym]"] = query.acronym
        return params

    @staticmethod
    def _normalize(row: dict[str, Any]) -> TeamItem:
        return TeamItem(
            id=int(row["id"]),
            name=str(row["name"]),
            acronym=row.get("acronym"),
            location=row.get("location"),
        )


__all__ = ["PandaScoreTeamAdapter"]
