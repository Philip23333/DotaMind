"""Translate the match capability contract into one collection request."""

from __future__ import annotations

from typing import Any

from app.vnext.capabilities.esports.match import (
    CompetitionSummary,
    MatchItem,
    MatchScore,
    MatchSearchInput,
    MatchSearchResult,
    SeriesSummary,
    TeamSummary,
)

from .client import PandaScoreClient


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
        if query.sort == "begin_at_asc":
            params["sort"] = "begin_at"
        elif query.sort == "begin_at_desc":
            params["sort"] = "-begin_at"
        return params

    @classmethod
    def _normalize(cls, row: dict[str, Any]) -> MatchItem:
        return MatchItem(
            id=int(row["id"]),
            name=row.get("name"),
            status=row.get("status"),
            scheduled_at=row.get("scheduled_at"),
            begin_at=row.get("begin_at"),
            end_at=row.get("end_at"),
            match_type=row.get("match_type"),
            number_of_games=row.get("number_of_games"),
            league=cls._competition(row.get("league")),
            series=cls._series(row.get("serie")),
            tournament=cls._competition(row.get("tournament")),
            opponents=cls._opponents(row.get("opponents")),
            results=cls._results(row.get("results")),
            winner_id=row.get("winner_id"),
        )

    @staticmethod
    def _competition(value: Any) -> CompetitionSummary | None:
        if not isinstance(value, dict) or value.get("id") is None:
            return None
        return CompetitionSummary(id=int(value["id"]), name=value.get("name"))

    @staticmethod
    def _series(value: Any) -> SeriesSummary | None:
        if not isinstance(value, dict) or value.get("id") is None:
            return None
        return SeriesSummary(
            id=int(value["id"]),
            name=value.get("name"),
            full_name=value.get("full_name"),
            year=value.get("year"),
        )

    @staticmethod
    def _opponents(value: Any) -> list[TeamSummary]:
        if not isinstance(value, list):
            return []
        result: list[TeamSummary] = []
        for wrapper in value:
            if not isinstance(wrapper, dict):
                continue
            opponent = wrapper.get("opponent")
            if not isinstance(opponent, dict) or opponent.get("id") is None:
                continue
            result.append(
                TeamSummary(
                    id=int(opponent["id"]),
                    name=opponent.get("name"),
                    acronym=opponent.get("acronym"),
                )
            )
        return result

    @staticmethod
    def _results(value: Any) -> list[MatchScore]:
        if not isinstance(value, list):
            return []
        result: list[MatchScore] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            team_id = item.get("team_id")
            score = item.get("score")
            if team_id is None or score is None:
                continue
            result.append(MatchScore(team_id=int(team_id), score=int(score)))
        return result


__all__ = ["PandaScoreMatchAdapter"]
