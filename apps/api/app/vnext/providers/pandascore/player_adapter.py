"""Translate the player capability contract into one collection request."""

from __future__ import annotations

import logging
from typing import Any

from app.vnext.capabilities.esports.dtos import (
    PlayerDTO,
    PlayerRole,
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
    def _normalize(cls, row: dict[str, Any]) -> PlayerDTO:
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
            current_team=cls._current_team(row.get("current_team")),
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
    def _current_team(cls, value: Any) -> TeamRefDTO | None:
        if value is None or not isinstance(value, dict):
            return None
        return TeamRefDTO(
            id=int(value["id"]),
            name=value["name"],
            acronym=cls._optional_text(value.get("acronym")),
            location=cls._optional_text(value.get("location")),
            slug=cls._optional_text(value.get("slug")),
            image_url=cls._optional_text(value.get("image_url")),
        )


__all__ = ["PandaScorePlayerAdapter"]
