"""PandaScore competition and stage normalization."""

from __future__ import annotations

from typing import Any

from app.integrations.pandascore.models import PandaCompetition, PandaTournamentStage
from app.integrations.pandascore.transport import PandaScoreTransport


class PandaScoreCompetitions:
    def __init__(self, transport: PandaScoreTransport) -> None:
        self.transport = transport

    async def list_series(
        self,
        query: str | None = None,
        year: int | None = None,
    ) -> list[PandaCompetition]:
        params: dict[str, Any] = {"page[size]": self.transport.max_page_size}
        if year is not None:
            params["filter[year]"] = year
        rows = await self.transport.get("/dota2/series", params=params)
        normalized = [normalize_competition(row) for row in rows if isinstance(row, dict)]
        if not query:
            return normalized
        needle = query.strip().casefold()
        return [
            row
            for row in normalized
            if needle in row.name.casefold()
            or needle in (row.full_name or "").casefold()
            or (
                row.full_name
                and row.league is not None
                and needle in f"{row.league.get('name', '')} {row.full_name}".casefold()
            )
            or (
                row.league is not None
                and needle in str(row.league.get("name") or "").casefold()
            )
        ]

    async def get_series(self, series_id: int) -> PandaCompetition | None:
        rows = await self.transport.get(
            "/dota2/series",
            params={"filter[id]": series_id, "page[size]": 10},
        )
        normalized = [normalize_competition(row) for row in rows if isinstance(row, dict)]
        return normalized[0] if normalized else None

    async def list_tournaments(self, series_id: int) -> list[PandaTournamentStage]:
        rows = await self.transport.get(
            "/dota2/tournaments",
            params={"filter[serie_id]": series_id, "page[size]": self.transport.max_page_size},
        )
        return [
            normalize_tournament(row)
            for row in rows
            if isinstance(row, dict) and row.get("id") is not None
        ]


def normalize_competition(row: dict[str, Any]) -> PandaCompetition:
    league = row.get("league") if isinstance(row.get("league"), dict) else None
    league_name = league.get("name") if league else None
    name = str(row.get("name") or league_name or row.get("full_name") or row["id"])
    return PandaCompetition(
        pandascore_series_id=int(row["id"]),
        name=name,
        full_name=row.get("full_name"),
        year=_as_int(row.get("year")),
        season=row.get("season"),
        league=league,
        tournaments=[
            _normalize_inline_tournament(item, int(row["id"]))
            for item in (row.get("tournaments") or [])
            if isinstance(item, dict) and item.get("id") is not None
        ],
    )


def normalize_tournament(row: dict[str, Any]) -> PandaTournamentStage:
    return PandaTournamentStage(
        pandascore_tournament_id=int(row["id"]),
        pandascore_series_id=int(row.get("serie_id") or row.get("series_id")),
        name=str(row.get("name") or row["id"]),
        begin_at=row.get("begin_at"),
        end_at=row.get("end_at"),
        tier=row.get("tier"),
        region=row.get("region"),
    )


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalize_inline_tournament(row: dict[str, Any], series_id: int) -> dict[str, Any]:
    return {
        "pandascore_tournament_id": int(row["id"]),
        "pandascore_series_id": _as_int(row.get("serie_id")) or series_id,
        "name": str(row.get("name") or row["id"]),
        "begin_at": row.get("begin_at"),
        "end_at": row.get("end_at"),
        "tier": row.get("tier"),
        "region": row.get("region"),
    }
