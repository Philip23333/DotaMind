"""Translate the player capability contract into one collection request."""

from __future__ import annotations

import logging
from typing import Any

from app.vnext.capabilities.esports.dtos import (
    PlayerDTO,
    PlayerRole,
    ResponseAnomaly,
    TeamRefDTO,
)
from app.vnext.capabilities.esports.player import (
    PlayerSearchInput,
    PlayerSearchResult,
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


class PandaScorePlayerAdapter:
    def __init__(self, client: PandaScoreClient) -> None:
        self.client = client

    async def search(self, query: PlayerSearchInput) -> PlayerSearchResult:
        rows = await self.client.get_list(
            "/dota2/players",
            params=self._params(query),
        )
        items: list[PlayerDTO] = []
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
                logger.warning("Failed to map PandaScore player item", exc_info=exc)
                anomalies.append(
                    ResponseAnomaly(
                        path=path,
                        reason=self._mapping_reason(exc),
                        provider_id=self._provider_id(row.get("id")),
                    )
                )
        return PlayerSearchResult(
            items=items,
            page=query.page,
            limit=query.limit,
            anomalies=anomalies,
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
    def _normalize(
        cls,
        row: dict[str, Any],
        *,
        path: str = "item",
        anomalies: list[ResponseAnomaly] | None = None,
    ) -> PlayerDTO:
        anomaly_list = anomalies if anomalies is not None else []
        return PlayerDTO(
            id=int(row["id"]),
            name=row["name"],
            active=row["active"],
            role=cls._player_role(row.get("role")),
            first_name=cls._optional_text(row.get("first_name")),
            last_name=cls._optional_text(row.get("last_name")),
            nationality=cls._optional_text(row.get("nationality")),
            slug=cls._optional_text(row.get("slug")),
            image_url=cls._optional_text(row.get("image_url")),
            current_team=cls._current_team(
                row.get("current_team"),
                path=f"{path}.current_team",
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
    def _current_team(
        cls,
        value: Any,
        *,
        path: str = "current_team",
        anomalies: list[ResponseAnomaly] | None = None,
    ) -> TeamRefDTO | None:
        if value is None:
            return None
        anomaly_list = anomalies if anomalies is not None else []
        if not isinstance(value, dict):
            anomaly_list.append(
                ResponseAnomaly(path=path, reason="invalid current_team relation")
            )
            return None
        try:
            return TeamRefDTO(
                id=int(value["id"]),
                name=value["name"],
                acronym=cls._optional_text(value.get("acronym")),
                location=cls._optional_text(value.get("location")),
                slug=cls._optional_text(value.get("slug")),
                image_url=cls._optional_text(value.get("image_url")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Failed to map PandaScore current_team relation", exc_info=exc)
            anomaly_list.append(
                ResponseAnomaly(
                    path=path,
                    reason="invalid current_team relation",
                    provider_id=cls._provider_id(value.get("id")),
                )
            )
            return None

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


__all__ = ["PandaScorePlayerAdapter"]
