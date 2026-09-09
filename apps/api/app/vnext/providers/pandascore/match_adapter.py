"""Translate the match capability contract into one collection request."""

from __future__ import annotations

import logging
from typing import Any

from app.vnext.capabilities.esports.dtos import (
    MatchDTO,
    MatchGameDTO,
    MatchParticipantDTO,
    ResponseAnomaly,
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
        items: list[MatchDTO] = []
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
                logger.warning("Failed to map PandaScore match item", exc_info=exc)
                anomalies.append(
                    ResponseAnomaly(
                        path=path,
                        reason=self._mapping_reason(exc),
                        provider_id=self._provider_id(row.get("id")),
                    )
                )
        return MatchSearchResult(
            items=items,
            page=query.page,
            limit=query.limit,
            anomalies=anomalies,
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
    def _normalize(
        cls,
        row: dict[str, Any],
        *,
        path: str = "item",
        anomalies: list[ResponseAnomaly] | None = None,
    ) -> MatchDTO:
        anomaly_list = anomalies if anomalies is not None else []
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
                path=path,
                anomalies=anomaly_list,
            ),
            winner_id=row.get("winner_id"),
            winner=cls._winner(
                row.get("winner"),
                path=f"{path}.winner",
                anomalies=anomaly_list,
            ),
            games=cls._games(
                row.get("games"),
                path=f"{path}.games",
                anomalies=anomaly_list,
            ),
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
        *,
        path: str = "item",
        anomalies: list[ResponseAnomaly] | None = None,
    ) -> list[MatchParticipantDTO]:
        anomaly_list = anomalies if anomalies is not None else []
        score_by_team_id: dict[int, int | None] = {}
        result_index_by_team_id: dict[int, int] = {}
        result_team_ids: set[int] = set()
        if results_value is None:
            results: list[Any] = []
        elif isinstance(results_value, list):
            results = results_value
        else:
            anomaly_list.append(
                ResponseAnomaly(
                    path=f"{path}.results",
                    reason="invalid nested results collection",
                )
            )
            results = []
        for index, item in enumerate(results):
            item_path = f"{path}.results[{index}]"
            if not isinstance(item, dict):
                anomaly_list.append(
                    ResponseAnomaly(
                        path=item_path,
                        reason="provider item is not an object",
                    )
                )
                continue
            try:
                normalized_team_id = int(item["team_id"])
                score = item.get("score")
                normalized_score = int(score) if score is not None else None
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Failed to map PandaScore match result", exc_info=exc)
                anomaly_list.append(
                    ResponseAnomaly(
                        path=item_path,
                        reason=cls._mapping_reason(exc),
                        provider_id=cls._provider_id(item.get("team_id")),
                    )
                )
                continue
            result_team_ids.add(normalized_team_id)
            result_index_by_team_id.setdefault(normalized_team_id, index)
            score_by_team_id[normalized_team_id] = normalized_score

        participants: list[MatchParticipantDTO] = []
        opponent_team_ids: set[int] = set()
        if opponents_value is None:
            opponents: list[Any] = []
        elif isinstance(opponents_value, list):
            opponents = opponents_value
        else:
            anomaly_list.append(
                ResponseAnomaly(
                    path=f"{path}.opponents",
                    reason="invalid nested opponents collection",
                )
            )
            opponents = []
        for index, wrapper in enumerate(opponents):
            wrapper_path = f"{path}.opponents[{index}]"
            if not isinstance(wrapper, dict):
                anomaly_list.append(
                    ResponseAnomaly(
                        path=wrapper_path,
                        reason="provider item is not an object",
                    )
                )
                continue
            opponent = wrapper.get("opponent")
            if not isinstance(opponent, dict):
                anomaly_list.append(
                    ResponseAnomaly(
                        path=f"{wrapper_path}.opponent",
                        reason="invalid opponent relation",
                    )
                )
                continue
            try:
                team = cls._map_team_ref(opponent)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Failed to map PandaScore match opponent", exc_info=exc)
                anomaly_list.append(
                    ResponseAnomaly(
                        path=f"{wrapper_path}.opponent",
                        reason=cls._mapping_reason(exc),
                        provider_id=cls._provider_id(opponent.get("id")),
                    )
                )
                continue
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
                anomaly_list.append(
                    ResponseAnomaly(
                        path=(
                            f"{path}.results[{result_index_by_team_id[team_id]}]"
                        ),
                        reason="result references unknown opponent",
                        provider_id=team_id,
                    )
                )

        return participants

    @classmethod
    def _winner(
        cls,
        value: Any,
        *,
        path: str = "winner",
        anomalies: list[ResponseAnomaly] | None = None,
    ) -> TeamRefDTO | None:
        if value is None:
            return None
        anomaly_list = anomalies if anomalies is not None else []
        if not isinstance(value, dict):
            anomaly_list.append(
                ResponseAnomaly(path=path, reason="invalid winner relation")
            )
            return None
        try:
            return cls._map_team_ref(value)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Failed to map PandaScore match winner", exc_info=exc)
            anomaly_list.append(
                ResponseAnomaly(
                    path=path,
                    reason="invalid winner relation",
                    provider_id=cls._provider_id(value.get("id")),
                )
            )
            return None

    @classmethod
    def _games(
        cls,
        value: Any,
        *,
        path: str = "games",
        anomalies: list[ResponseAnomaly] | None = None,
    ) -> list[MatchGameDTO]:
        if value is None:
            return []
        anomaly_list = anomalies if anomalies is not None else []
        if not isinstance(value, list):
            anomaly_list.append(
                ResponseAnomaly(path=path, reason="invalid nested games collection")
            )
            return []
        result: list[MatchGameDTO] = []
        for index, game in enumerate(value):
            game_path = f"{path}[{index}]"
            if not isinstance(game, dict):
                anomaly_list.append(
                    ResponseAnomaly(
                        path=game_path,
                        reason="provider item is not an object",
                    )
                )
                continue
            winner = game.get("winner")
            winner_id = None
            if winner is not None:
                try:
                    if not isinstance(winner, dict):
                        raise TypeError("winner")
                    winner_id = int(winner["id"])
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning("Failed to map PandaScore game winner", exc_info=exc)
                    anomaly_list.append(
                        ResponseAnomaly(
                            path=f"{game_path}.winner",
                            reason="invalid winner relation",
                            provider_id=cls._provider_id(
                                winner.get("id") if isinstance(winner, dict) else None
                            ),
                        )
                    )
            try:
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
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Failed to map PandaScore game", exc_info=exc)
                anomaly_list.append(
                    ResponseAnomaly(
                        path=game_path,
                        reason=cls._mapping_reason(exc),
                        provider_id=cls._provider_id(game.get("id")),
                    )
                )
        return result

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


__all__ = ["PandaScoreMatchAdapter"]
