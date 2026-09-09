"""Translate the tournament capability contract into one collection request."""

from __future__ import annotations

import logging
from typing import Any

from app.vnext.capabilities.esports.dtos import (
    ResponseAnomaly,
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

logger = logging.getLogger(__name__)


class PandaScoreTournamentAdapter:
    def __init__(self, client: PandaScoreClient) -> None:
        self.client = client

    async def search(self, query: TournamentSearchInput) -> TournamentSearchResult:
        rows = await self.client.get_list(
            "/dota2/tournaments",
            params=self._params(query),
        )
        items: list[TournamentDTO] = []
        anomalies: list[ResponseAnomaly] = []
        for index, row in enumerate(rows):
            path = f"items[{index}]"
            if not isinstance(row, dict):
                anomalies.append(
                    ResponseAnomaly(path=path, reason="provider item is not an object")
                )
                continue
            try:
                items.append(self._normalize(row, path=path, anomalies=anomalies))
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Failed to map PandaScore tournament item", exc_info=exc)
                anomalies.append(
                    ResponseAnomaly(
                        path=path,
                        reason=self._mapping_reason(exc),
                        provider_id=self._provider_id(row.get("id")),
                    )
                )
        return TournamentSearchResult(
            items=items,
            page=query.page,
            limit=query.limit,
            anomalies=anomalies,
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
    def _normalize(
        cls,
        row: dict[str, Any],
        *,
        path: str = "item",
        anomalies: list[ResponseAnomaly] | None = None,
    ) -> TournamentDTO:
        anomaly_list = anomalies if anomalies is not None else []
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
                path=path,
                anomalies=anomaly_list,
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
        *,
        path: str = "item",
        anomalies: list[ResponseAnomaly] | None = None,
    ) -> list[TournamentParticipantDTO]:
        anomaly_list = anomalies if anomalies is not None else []
        roster_team_by_id: dict[int, TeamRefDTO] = {}
        roster_players_by_team_id: dict[int, list[TournamentRosterPlayerDTO]] = {}
        roster_team_order: list[int] = []

        if expected_roster_value is None:
            expected_roster: list[Any] = []
        elif isinstance(expected_roster_value, list):
            expected_roster = expected_roster_value
        else:
            anomaly_list.append(
                ResponseAnomaly(
                    path=f"{path}.expected_roster",
                    reason="invalid nested expected_roster collection",
                )
            )
            expected_roster = []

        for index, entry in enumerate(expected_roster):
            entry_path = f"{path}.expected_roster[{index}]"
            if not isinstance(entry, dict):
                anomaly_list.append(
                    ResponseAnomaly(
                        path=entry_path,
                        reason="provider item is not an object",
                    )
                )
                continue
            try:
                team_ref = cls._map_team_ref(entry["team"])
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Failed to map tournament roster team", exc_info=exc)
                anomaly_list.append(
                    ResponseAnomaly(
                        path=f"{entry_path}.team",
                        reason=cls._mapping_reason(exc),
                        provider_id=cls._provider_id(
                            entry.get("team", {}).get("id")
                            if isinstance(entry.get("team"), dict)
                            else None
                        ),
                    )
                )
                continue
            team_id = team_ref.id
            if team_id not in roster_team_by_id:
                roster_team_by_id[team_id] = team_ref
                roster_team_order.append(team_id)
                roster_players_by_team_id[team_id] = []
            players = entry.get("players")
            if players is None:
                continue
            if not isinstance(players, list):
                anomaly_list.append(
                    ResponseAnomaly(
                        path=f"{entry_path}.players",
                        reason="invalid nested players collection",
                    )
                )
                continue
            for player_index, player in enumerate(players):
                player_path = f"{entry_path}.players[{player_index}]"
                if not isinstance(player, dict):
                    anomaly_list.append(
                        ResponseAnomaly(
                            path=player_path,
                            reason="provider item is not an object",
                        )
                    )
                    continue
                try:
                    roster_players_by_team_id[team_id].append(
                        cls._map_roster_player(player)
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning("Failed to map tournament roster player", exc_info=exc)
                    anomaly_list.append(
                        ResponseAnomaly(
                            path=player_path,
                            reason=cls._mapping_reason(exc),
                            provider_id=cls._provider_id(player.get("id")),
                        )
                    )

        participants: list[TournamentParticipantDTO] = []
        team_ids: set[int] = set()
        if teams_value is None:
            teams: list[Any] = []
        elif isinstance(teams_value, list):
            teams = teams_value
        else:
            anomaly_list.append(
                ResponseAnomaly(
                    path=f"{path}.teams",
                    reason="invalid nested teams collection",
                )
            )
            teams = []
        for index, team_row in enumerate(teams):
            team_path = f"{path}.teams[{index}]"
            if not isinstance(team_row, dict):
                anomaly_list.append(
                    ResponseAnomaly(
                        path=team_path,
                        reason="provider item is not an object",
                    )
                )
                continue
            try:
                team_ref = cls._map_team_ref(team_row)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Failed to map tournament team", exc_info=exc)
                anomaly_list.append(
                    ResponseAnomaly(
                        path=team_path,
                        reason=cls._mapping_reason(exc),
                        provider_id=cls._provider_id(team_row.get("id")),
                    )
                )
                continue
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

    @staticmethod
    def _provider_id(value: Any) -> int | None:
        if isinstance(value, bool) or value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _mapping_reason(exc: Exception) -> str:
        if isinstance(exc, KeyError) and exc.args:
            return f"missing required field: {exc.args[0]}"
        return "failed to map provider item"


__all__ = ["PandaScoreTournamentAdapter"]
