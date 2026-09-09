"""Translate the team capability contract into one collection request."""

from __future__ import annotations

import logging
from typing import Any

from app.vnext.capabilities.esports.dtos import (
    CurrentRosterPlayerDTO,
    PlayerRole,
    ResponseAnomaly,
    TeamDTO,
)
from app.vnext.capabilities.esports.team import (
    TeamSearchInput,
    TeamSearchResult,
)

from .client import PandaScoreClient

logger = logging.getLogger(__name__)

_PLAYER_ROLE_BY_POSITION = {
    "1": PlayerRole.carry,
    "2": PlayerRole.mid,
    "3": PlayerRole.offlane,
    "4": PlayerRole.soft_support,
    "5": PlayerRole.hard_support,
}


class PandaScoreTeamAdapter:
    def __init__(self, client: PandaScoreClient) -> None:
        self.client = client

    async def search(self, query: TeamSearchInput) -> TeamSearchResult:
        rows = await self.client.get_list(
            "/dota2/teams",
            params=self._params(query),
        )
        items: list[TeamDTO] = []
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
                logger.warning("Failed to map PandaScore team item", exc_info=exc)
                anomalies.append(
                    ResponseAnomaly(
                        path=path,
                        reason=self._mapping_reason(exc),
                        provider_id=self._provider_id(row.get("id")),
                    )
                )
        return TeamSearchResult(
            items=items,
            page=query.page,
            limit=query.limit,
            anomalies=anomalies,
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

    @classmethod
    def _normalize(
        cls,
        row: dict[str, Any],
        *,
        path: str = "item",
        anomalies: list[ResponseAnomaly] | None = None,
    ) -> TeamDTO:
        anomaly_list = anomalies if anomalies is not None else []
        return TeamDTO(
            id=int(row["id"]),
            name=row["name"],
            acronym=cls._optional_text(row.get("acronym")),
            location=cls._optional_text(row.get("location")),
            slug=cls._optional_text(row.get("slug")),
            image_url=cls._optional_text(row.get("image_url")),
            current_roster=cls._current_roster(
                row.get("players"),
                path=f"{path}.players",
                anomalies=anomaly_list,
            ),
        )

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _player_role(value: Any) -> tuple[PlayerRole, ...] | None:
        if value is None:
            return None
        if isinstance(value, bool):
            logger.warning("Unknown PandaScore player role value=%r", value)
            return None
        if isinstance(value, int):
            tokens = [str(value)]
        elif isinstance(value, str):
            tokens = [token.strip() for token in value.split("/")]
        else:
            logger.warning("Unknown PandaScore player role value=%r", value)
            return None

        if not tokens or any(token not in _PLAYER_ROLE_BY_POSITION for token in tokens):
            logger.warning("Unknown PandaScore player role value=%r", value)
            return None
        return tuple(_PLAYER_ROLE_BY_POSITION[token] for token in tokens)

    @classmethod
    def _map_current_roster_player(
        cls,
        row: dict[str, Any],
    ) -> CurrentRosterPlayerDTO:
        return CurrentRosterPlayerDTO(
            id=int(row["id"]),
            name=row["name"],
            active=row["active"],
            role=cls._player_role(row.get("role")),
            first_name=cls._optional_text(row.get("first_name")),
            last_name=cls._optional_text(row.get("last_name")),
            nationality=cls._optional_text(row.get("nationality")),
            slug=cls._optional_text(row.get("slug")),
            image_url=cls._optional_text(row.get("image_url")),
        )

    @classmethod
    def _current_roster(
        cls,
        value: Any,
        *,
        path: str = "players",
        anomalies: list[ResponseAnomaly] | None = None,
    ) -> list[CurrentRosterPlayerDTO]:
        if value is None:
            return []
        anomaly_list = anomalies if anomalies is not None else []
        if not isinstance(value, list):
            anomaly_list.append(
                ResponseAnomaly(path=path, reason="invalid nested players collection")
            )
            return []
        result: list[CurrentRosterPlayerDTO] = []
        for index, row in enumerate(value):
            item_path = f"{path}[{index}]"
            if not isinstance(row, dict):
                anomaly_list.append(
                    ResponseAnomaly(
                        path=item_path,
                        reason="provider item is not an object",
                    )
                )
                continue
            try:
                result.append(cls._map_current_roster_player(row))
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Failed to map PandaScore roster player", exc_info=exc)
                anomaly_list.append(
                    ResponseAnomaly(
                        path=item_path,
                        reason=cls._mapping_reason(exc),
                        provider_id=cls._provider_id(row.get("id")),
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


__all__ = ["PandaScoreTeamAdapter"]
