"""Translate the match capability contract into one collection request."""

from __future__ import annotations

import logging
from typing import Any

from app.vnext.capabilities.esports.dtos import (
    MatchDTO,
    MatchGameDTO,
    MatchParticipantDTO,
    TeamRefDTO,
)
from app.vnext.capabilities.esports.match import MatchSearchInput, MatchSearchResult

from .client import PandaScoreClient

logger = logging.getLogger(__name__)


class PandaScoreMatchAdapter:
    def __init__(self, client: PandaScoreClient) -> None:
        self.client = client

    async def search(self, query: MatchSearchInput) -> MatchSearchResult:
        rows = await self.client.get_list(
            self._path(query.lifecycle),
            params=self._params(query),
        )
        return MatchSearchResult(
            items=[self._normalize(row) for row in rows],
            page=query.page,
            limit=query.limit,
        )

    @staticmethod
    def _path(lifecycle: str | None) -> str:
        if lifecycle is None:
            return "/dota2/matches"
        return f"/dota2/matches/{lifecycle}"

    @staticmethod
    def _params(query: MatchSearchInput) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": query.page,
            "per_page": query.limit,
        }
        if query.id is not None:
            params["filter[id]"] = query.id
        if query.league_id is not None:
            params["filter[league_id]"] = query.league_id
        if query.series_id is not None:
            params["filter[serie_id]"] = query.series_id
        if query.tournament_id is not None:
            params["filter[tournament_id]"] = query.tournament_id
        if query.team_id is not None:
            params["filter[opponent_id]"] = query.team_id
        if query.name is not None:
            params["search[name]"] = query.name
        if query.status is not None:
            params["filter[status]"] = query.status
        if query.winner_id is not None:
            params["filter[winner_id]"] = query.winner_id
        if query.sort == "begin_at_asc":
            params["sort"] = "begin_at"
        elif query.sort == "begin_at_desc":
            params["sort"] = "-begin_at"
        return params

    @classmethod
    def _normalize(cls, row: dict[str, Any]) -> MatchDTO:
        return MatchDTO(
            id=int(row["id"]),
            name=row["name"],
            slug=cls._optional_text(row.get("slug")),
            status=row["status"],
            match_type=cls._optional_text(row.get("match_type")),
            number_of_games=row.get("number_of_games"),
            begin_at=row.get("begin_at"),
            end_at=row.get("end_at"),
            scheduled_at=row.get("scheduled_at"),
            original_scheduled_at=row.get("original_scheduled_at"),
            league_id=(
                int(row["league_id"]) if row.get("league_id") is not None else None
            ),
            series_id=(
                int(row["serie_id"]) if row.get("serie_id") is not None else None
            ),
            tournament_id=(
                int(row["tournament_id"])
                if row.get("tournament_id") is not None
                else None
            ),
            participants=cls._participants(
                row.get("opponents"),
                row.get("results"),
                int(row["id"]),
            ),
            winner_id=row.get("winner_id"),
            winner=cls._winner(row.get("winner")),
            games=cls._games(row.get("games")),
            draw=row["draw"],
            forfeit=row["forfeit"],
            rescheduled=row["rescheduled"],
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
    def _participants(
        cls,
        opponents_value: Any,
        results_value: Any,
        match_id: int,
    ) -> list[MatchParticipantDTO]:
        score_by_team_id: dict[int, int | None] = {}
        result_team_ids: set[int] = set()
        results = results_value if isinstance(results_value, list) else []
        for item in results:
            if not isinstance(item, dict):
                continue
            team_id = item.get("team_id")
            score = item.get("score")
            if team_id is None:
                continue
            normalized_team_id = int(team_id)
            result_team_ids.add(normalized_team_id)
            if score is not None:
                score_by_team_id[normalized_team_id] = int(score)

        participants: list[MatchParticipantDTO] = []
        opponent_team_ids: set[int] = set()
        opponents = opponents_value if isinstance(opponents_value, list) else []
        for wrapper in opponents:
            if not isinstance(wrapper, dict):
                continue
            opponent = wrapper.get("opponent")
            if not isinstance(opponent, dict) or opponent.get("id") is None:
                continue
            team = cls._map_team_ref(opponent)
            opponent_team_ids.add(team.id)
            participants.append(
                MatchParticipantDTO(
                    team=team,
                    score=score_by_team_id.get(team.id),
                )
            )

        for team_id in result_team_ids:
            if team_id not in opponent_team_ids:
                logger.warning(
                    "Ignoring Match result for unknown opponent team_id=%s in match id=%s",
                    team_id,
                    match_id,
                )

        return participants

    @classmethod
    def _winner(cls, value: Any) -> TeamRefDTO | None:
        if not isinstance(value, dict) or value.get("id") is None:
            return None
        return cls._map_team_ref(value)

    @staticmethod
    def _games(value: Any) -> list[MatchGameDTO]:
        if not isinstance(value, list):
            return []
        result: list[MatchGameDTO] = []
        for game in value:
            if not isinstance(game, dict):
                continue
            winner = game.get("winner")
            winner_id = (
                int(winner["id"])
                if isinstance(winner, dict) and winner.get("id") is not None
                else None
            )
            result.append(
                MatchGameDTO(
                    id=int(game["id"]),
                    position=int(game["position"]),
                    status=game["status"],
                    begin_at=game.get("begin_at"),
                    end_at=game.get("end_at"),
                    length=game.get("length"),
                    winner_id=winner_id,
                    complete=game["complete"],
                    forfeit=game["forfeit"],
                )
            )
        return result


__all__ = ["PandaScoreMatchAdapter"]
