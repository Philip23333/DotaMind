"""Translate the tournament capability contract into one collection request."""

from __future__ import annotations

from typing import Any

from app.vnext.capabilities.esports.tournament import (
    TournamentItem,
    TournamentRosterItem,
    TournamentRosterPlayer,
    TournamentRostersInput,
    TournamentRostersResult,
    TournamentRosterTeam,
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

    async def rosters(self, query: TournamentRostersInput) -> TournamentRostersResult:
        rows = await self.client.get_list(
            f"/tournaments/{query.tournament_id}/rosters",
            params={},
        )
        items = [self._normalize_roster(row) for row in rows]
        if query.team_id is not None:
            items = [item for item in items if item.team.id == query.team_id]
        return TournamentRostersResult(items=items)

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

    @classmethod
    def _normalize_roster(cls, row: dict[str, Any]) -> TournamentRosterItem:
        team = row["team"]
        if not isinstance(team, dict):
            raise ValueError("tournament roster team must be an object")
        return TournamentRosterItem(
            team=TournamentRosterTeam(
                id=int(team["id"]),
                name=str(team["name"]),
                acronym=team.get("acronym"),
            ),
            players=cls._normalize_roster_players(row.get("players")),
        )

    @staticmethod
    def _normalize_roster_players(value: Any) -> list[TournamentRosterPlayer]:
        if not isinstance(value, list):
            return []
        players: list[TournamentRosterPlayer] = []
        for player in value:
            if not isinstance(player, dict):
                continue
            if player.get("id") is None or player.get("name") is None:
                continue
            players.append(
                TournamentRosterPlayer(
                    id=int(player["id"]),
                    name=str(player["name"]),
                    first_name=player.get("first_name"),
                    last_name=player.get("last_name"),
                    role=player.get("role"),
                )
            )
        return players


__all__ = ["PandaScoreTournamentAdapter"]
