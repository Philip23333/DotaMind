"""Translate the tournament capability contract into one collection request."""

from __future__ import annotations

from typing import Any

from app.vnext.capabilities.esports.tournament import (
    TournamentItem,
    TournamentSearchInput,
    TournamentSearchResult,
)

from .client import PandaScoreClient


class PandaScoreTournamentAdapter:
    def __init__(self, client: PandaScoreClient) -> None:
        self.client = client

    async def search(self, query: TournamentSearchInput) -> TournamentSearchResult:
        rows = await self.client.get_list(
            "/dota2/tournaments",
            params=self._params(query),
        )
        return TournamentSearchResult(
            items=[self._normalize(row) for row in rows],
            page=query.page,
            limit=query.limit,
        )

    @staticmethod
    def _params(query: TournamentSearchInput) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": query.page,
            "per_page": query.limit,
        }
        if query.id is not None:
            params["filter[id]"] = query.id
        if query.series_id is not None:
            params["filter[serie_id]"] = query.series_id
        if query.name is not None:
            params["search[name]"] = query.name
        return params

    @staticmethod
    def _normalize(row: dict[str, Any]) -> TournamentItem:
        series_id = row.get("serie_id")
        if series_id is None:
            serie = row.get("serie")
            if isinstance(serie, dict):
                series_id = serie.get("id")

        return TournamentItem(
            id=int(row["id"]),
            name=str(row["name"]),
            series_id=int(series_id) if series_id is not None else None,
            begin_at=row.get("begin_at"),
            end_at=row.get("end_at"),
        )


__all__ = ["PandaScoreTournamentAdapter"]
