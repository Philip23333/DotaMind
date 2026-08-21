"""OpenDota league catalog and league-match access."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.integrations.opendota.transport import OpenDotaTransport


class OpenDotaLeague(BaseModel):
    opendota_league_id: int
    name: str
    tier: str | None = None


class OpenDotaLeagueMatch(BaseModel):
    valve_match_id: int
    opendota_league_id: int
    opendota_series_id: int | None = None
    series_type: int | None = None
    start_time: int | None = None
    duration: int | None = None
    radiant_team_id: int | None = None
    dire_team_id: int | None = None
    radiant_win: bool | None = None
    radiant_score: int | None = None
    dire_score: int | None = None


class OpenDotaLeagues:
    def __init__(self, transport: OpenDotaTransport) -> None:
        self.transport = transport

    async def get_all(self) -> list[OpenDotaLeague]:
        rows = await self.transport.get("leagues", "/leagues")
        if not isinstance(rows, list):
            raise ValueError("OpenDota leagues response must be a list")
        return [normalize_league(row) for row in rows if isinstance(row, dict)]

    async def get_matches(self, league_id: int) -> list[OpenDotaLeagueMatch]:
        rows = await self.transport.get(
            f"league_matches_{league_id}", f"/leagues/{league_id}/matches"
        )
        if not isinstance(rows, list):
            raise ValueError("OpenDota league matches response must be a list")
        return [
            normalize_league_match(row, league_id)
            for row in rows
            if isinstance(row, dict) and row.get("match_id") is not None
        ]


def normalize_league(row: dict[str, Any]) -> OpenDotaLeague:
    return OpenDotaLeague(
        opendota_league_id=int(row["leagueid"]),
        name=str(row.get("name") or row["leagueid"]),
        tier=row.get("tier"),
    )


def normalize_league_match(
    row: dict[str, Any], league_id: int | None = None
) -> OpenDotaLeagueMatch:
    resolved_league_id = row.get("leagueid") or league_id
    if resolved_league_id is None:
        raise ValueError("OpenDota league match is missing league id")
    return OpenDotaLeagueMatch(
        valve_match_id=int(row["match_id"]),
        opendota_league_id=int(resolved_league_id),
        opendota_series_id=_as_int(row.get("series_id")),
        series_type=_as_int(row.get("series_type")),
        start_time=_as_int(row.get("start_time")),
        duration=_as_int(row.get("duration")),
        radiant_team_id=_as_int(row.get("radiant_team_id")),
        dire_team_id=_as_int(row.get("dire_team_id")),
        radiant_win=row.get("radiant_win"),
        radiant_score=_as_int(row.get("radiant_score")),
        dire_score=_as_int(row.get("dire_score")),
    )


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
