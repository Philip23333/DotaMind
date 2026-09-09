"""Translate the league capability contract into one collection request."""

from __future__ import annotations

import logging
from typing import Any

from app.vnext.capabilities.esports.dtos import LeagueDTO, ResponseAnomaly
from app.vnext.capabilities.esports.league import LeagueSearchInput, LeagueSearchResult

from .client import PandaScoreClient

logger = logging.getLogger(__name__)


class PandaScoreLeagueAdapter:
    def __init__(self, client: PandaScoreClient) -> None:
        self.client = client

    async def search(self, query: LeagueSearchInput) -> LeagueSearchResult:
        rows = await self.client.get_list(
            "/dota2/leagues",
            params=self._params(query),
        )
        items: list[LeagueDTO] = []
        anomalies: list[ResponseAnomaly] = []
        for index, row in enumerate(rows):
            path = f"items[{index}]"
            if not isinstance(row, dict):
                anomalies.append(
                    ResponseAnomaly(path=path, reason="provider item is not an object")
                )
                continue
            try:
                items.append(self._normalize(row))
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Failed to map PandaScore league item", exc_info=exc)
                anomalies.append(
                    ResponseAnomaly(
                        path=path,
                        reason=self._mapping_reason(exc),
                        provider_id=self._provider_id(row.get("id")),
                    )
                )
        return LeagueSearchResult(
            items=items,
            page=query.page,
            limit=query.limit,
            anomalies=anomalies,
        )

    @staticmethod
    def _params(query: LeagueSearchInput) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": query.page,
            "per_page": query.limit,
        }
        if query.id is not None:
            params["filter[id]"] = query.id
        if query.name is not None:
            params["search[name]"] = query.name
        return params

    @staticmethod
    def _normalize(row: dict[str, Any]) -> LeagueDTO:
        return LeagueDTO(
            id=int(row["id"]),
            name=row["name"],
            slug=PandaScoreLeagueAdapter._optional_text(row.get("slug")),
            image_url=PandaScoreLeagueAdapter._optional_text(row.get("image_url")),
        )

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

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


__all__ = ["PandaScoreLeagueAdapter"]
