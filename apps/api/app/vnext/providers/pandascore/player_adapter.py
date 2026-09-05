"""Translate the player capability contract into one collection request."""

from __future__ import annotations

from typing import Any

from app.vnext.capabilities.esports.player import (
    PlayerItem,
    PlayerSearchInput,
    PlayerSearchResult,
    PlayerTeamSummary,
)

from .client import PandaScoreClient


class PandaScorePlayerAdapter:
    def __init__(self, client: PandaScoreClient) -> None:
        self.client = client

    async def search(self, query: PlayerSearchInput) -> PlayerSearchResult:
        rows = await self.client.get_list(
            "/dota2/players",
            params=self._params(query),
        )
        return PlayerSearchResult(
            items=[self._normalize(row) for row in rows],
            page=query.page,
            limit=query.limit,
        )

    @staticmethod
    def _params(query: PlayerSearchInput) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": query.page,
            "per_page": query.limit,
        }
        if query.id is not None:
            params["filter[id]"] = query.id
        if query.team_id is not None:
            params["filter[team_id]"] = query.team_id
        if query.active is not None:
            params["filter[active]"] = query.active
        if query.name is not None:
            params["search[name]"] = query.name
        if query.first_name is not None:
            params["search[first_name]"] = query.first_name
        if query.last_name is not None:
            params["search[last_name]"] = query.last_name
        return params

    @classmethod
    def _normalize(cls, row: dict[str, Any]) -> PlayerItem:
        return PlayerItem(
            id=int(row["id"]),
            name=str(row["name"]),
            first_name=row.get("first_name"),
            last_name=row.get("last_name"),
            active=bool(row["active"]),
            nationality=row.get("nationality"),
            role=row.get("role"),
            current_team=cls._current_team(row.get("current_team")),
        )

    @staticmethod
    def _current_team(value: Any) -> PlayerTeamSummary | None:
        if not isinstance(value, dict) or value.get("id") is None or value.get("name") is None:
            return None
        return PlayerTeamSummary(
            id=int(value["id"]),
            name=str(value["name"]),
            acronym=value.get("acronym"),
        )


__all__ = ["PandaScorePlayerAdapter"]
