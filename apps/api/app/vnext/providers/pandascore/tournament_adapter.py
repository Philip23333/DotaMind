"""Translate the tournament capability contract into one collection request."""

from __future__ import annotations

from typing import Any

from app.vnext.capabilities.esports.dtos import (
    TeamRefDTO,
    TournamentDTO,
    TournamentParticipantDTO,
    TournamentRosterPlayerDTO,
)
from app.vnext.capabilities.esports.tournament import (
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

    @classmethod
    def _normalize(cls, row: dict[str, Any]) -> TournamentDTO:
        return TournamentDTO(
            id=int(row["id"]),
            series_id=int(row["serie_id"]),
            league_id=int(row["league_id"]),
            name=row["name"],
            type=cls._optional_text(row.get("type")),
            country=cls._optional_text(row.get("country")),
            region=cls._optional_text(row.get("region")),
            begin_at=row.get("begin_at"),
            end_at=row.get("end_at"),
            winner_id=row.get("winner_id"),
            tier=cls._optional_text(row.get("tier")),
            prizepool=cls._optional_text(row.get("prizepool")),
            has_bracket=row.get("has_bracket"),
            slug=cls._optional_text(row.get("slug")),
            participants=cls._participants(
                row.get("teams"),
                row.get("expected_roster"),
            ),
        )

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @classmethod
    def _map_team_ref(cls, row: dict[str, Any]) -> TeamRefDTO:
        return TeamRefDTO(
            id=int(row["id"]),
            name=row["name"],
            acronym=cls._optional_text(row.get("acronym")),
            location=cls._optional_text(row.get("location")),
            slug=cls._optional_text(row.get("slug")),
            image_url=cls._optional_text(row.get("image_url")),
        )

    @classmethod
    def _map_roster_player(cls, row: dict[str, Any]) -> TournamentRosterPlayerDTO:
        return TournamentRosterPlayerDTO(
            id=int(row["id"]),
            name=row["name"],
            first_name=cls._optional_text(row.get("first_name")),
            last_name=cls._optional_text(row.get("last_name")),
            nationality=cls._optional_text(row.get("nationality")),
            slug=cls._optional_text(row.get("slug")),
        )

    @classmethod
    def _participants(
        cls,
        teams_value: Any,
        expected_roster_value: Any,
    ) -> list[TournamentParticipantDTO]:
        roster_team_by_id: dict[int, TeamRefDTO] = {}
        roster_players_by_team_id: dict[int, list[TournamentRosterPlayerDTO]] = {}
        roster_team_order: list[int] = []

        expected_roster = (
            expected_roster_value if isinstance(expected_roster_value, list) else []
        )
        for entry in expected_roster:
            if not isinstance(entry, dict):
                continue
            team_row = entry["team"]
            team_ref = cls._map_team_ref(team_row)
            team_id = team_ref.id
            if team_id not in roster_team_by_id:
                roster_team_by_id[team_id] = team_ref
                roster_team_order.append(team_id)
                roster_players_by_team_id[team_id] = []
            players = entry.get("players")
            if isinstance(players, list):
                roster_players_by_team_id[team_id].extend(
                    cls._map_roster_player(player) for player in players
                )

        participants: list[TournamentParticipantDTO] = []
        team_ids: set[int] = set()
        teams = teams_value if isinstance(teams_value, list) else []
        for team_row in teams:
            team_ref = cls._map_team_ref(team_row)
            team_ids.add(team_ref.id)
            participants.append(
                TournamentParticipantDTO(
                    team=team_ref,
                    expected_roster=roster_players_by_team_id.get(team_ref.id, []),
                )
            )

        for team_id in roster_team_order:
            if team_id in team_ids:
                continue
            participants.append(
                TournamentParticipantDTO(
                    team=roster_team_by_id[team_id],
                    expected_roster=roster_players_by_team_id[team_id],
                )
            )

        return participants


__all__ = ["PandaScoreTournamentAdapter"]
