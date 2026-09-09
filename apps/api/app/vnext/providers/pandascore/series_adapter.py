"""Translate the series capability contract into one collection request."""

from __future__ import annotations

import logging
from typing import Any

from app.vnext.capabilities.esports.dtos import (
    ResponseAnomaly,
    SeriesDTO,
    TeamRefDTO,
)
from app.vnext.capabilities.esports.series import (
    SeriesSearchInput,
    SeriesSearchResult,
    SeriesTeamsInput,
    SeriesTeamsResult,
)

from .client import PandaScoreClient

logger = logging.getLogger(__name__)


class PandaScoreSeriesAdapter:
    def __init__(self, client: PandaScoreClient) -> None:
        self.client = client

    async def search(self, query: SeriesSearchInput) -> SeriesSearchResult:
        rows = await self.client.get_list(
            "/dota2/series",
            params=self._params(query),
        )
        items: list[SeriesDTO] = []
        anomalies: list[ResponseAnomaly] = []
        for index, row in enumerate(rows):
            path = f"provider.items[{index}]"
            if not isinstance(row, dict):
                anomalies.append(
                    ResponseAnomaly(path=path, reason="provider item is not an object")
                )
                continue
            try:
                items.append(self._normalize(row))
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Failed to map PandaScore series item", exc_info=exc)
                anomalies.append(
                    ResponseAnomaly(
                        path=path,
                        reason=self._mapping_reason(exc),
                        provider_id=self._provider_id(row.get("id")),
                    )
                )
        return SeriesSearchResult(
            items=items,
            page=query.page,
            limit=query.limit,
            anomalies=anomalies,
        )

    async def teams(self, query: SeriesTeamsInput) -> SeriesTeamsResult:
        rows = await self.client.get_list(
            f"/dota2/series/{query.series_id}/teams",
            params={"page": query.page, "per_page": query.limit},
        )
        items: list[TeamRefDTO] = []
        anomalies: list[ResponseAnomaly] = []
        for index, row in enumerate(rows):
            path = f"provider.items[{index}]"
            if not isinstance(row, dict):
                anomalies.append(
                    ResponseAnomaly(path=path, reason="provider item is not an object")
                )
                continue
            try:
                items.append(self._normalize_team(row))
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Failed to map PandaScore series team item", exc_info=exc)
                anomalies.append(
                    ResponseAnomaly(
                        path=path,
                        reason=self._mapping_reason(exc),
                        provider_id=self._provider_id(row.get("id")),
                    )
                )
        return SeriesTeamsResult(
            items=items,
            page=query.page,
            limit=query.limit,
            anomalies=anomalies,
        )

    @staticmethod
    def _params(query: SeriesSearchInput) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": query.page,
            "per_page": query.limit,
        }
        if query.id is not None:
            params["filter[id]"] = query.id
        if query.league_id is not None:
            params["filter[league_id]"] = query.league_id
        if query.season is not None:
            params["filter[season]"] = query.season
        if query.year is not None:
            params["filter[year]"] = query.year
        if query.winner_id is not None:
            params["filter[winner_id]"] = query.winner_id
        if query.tier is not None:
            params["filter[tier]"] = query.tier
        if query.name is not None:
            params["search[name]"] = query.name
        return params

    @classmethod
    def _normalize(cls, row: dict[str, Any]) -> SeriesDTO:
        return SeriesDTO(
            id=int(row["id"]),
            league_id=int(row["league_id"]),
            name=cls._optional_text(row.get("name")),
            full_name=cls._optional_text(row.get("full_name")),
            year=row.get("year"),
            season=cls._optional_text(row.get("season")),
            begin_at=row.get("begin_at"),
            end_at=row.get("end_at"),
            winner_id=row.get("winner_id"),
            tier=cls._optional_text(row.get("tier")),
            slug=cls._optional_text(row.get("slug")),
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

    @classmethod
    def _normalize_team(cls, row: dict[str, Any]) -> TeamRefDTO:
        return TeamRefDTO(
            id=int(row["id"]),
            name=row["name"],
            acronym=cls._optional_text(row.get("acronym")),
            location=cls._optional_text(row.get("location")),
            slug=cls._optional_text(row.get("slug")),
            image_url=cls._optional_text(row.get("image_url")),
        )


__all__ = ["PandaScoreSeriesAdapter"]
