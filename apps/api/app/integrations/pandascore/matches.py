"""PandaScore fixture listing and game resolution."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from app.integrations.pandascore.competitions import PandaScoreCompetitions
from app.integrations.pandascore.models import (
    PandaCoverage,
    PandaGameReference,
    PandaMatchFixture,
    ResolvedMatchGames,
)
from app.integrations.pandascore.transport import PandaScoreTransport


class PandaScoreMatches:
    def __init__(
        self,
        transport: PandaScoreTransport,
        competitions: PandaScoreCompetitions,
    ) -> None:
        self.transport = transport
        self.competitions = competitions

    async def list_matches(
        self, series_id: int, *, limit: int | None = None
    ) -> list[PandaMatchFixture]:
        page_size = min(limit or self.transport.max_page_size, self.transport.max_page_size)
        all_rows: dict[int, PandaMatchFixture] = {}
        for endpoint in ("upcoming", "running", "past"):
            rows = await self.transport.get(
                f"/dota2/matches/{endpoint}",
                params={
                    "filter[serie_id]": series_id,
                    "sort": "-scheduled_at",
                    "page[size]": page_size,
                },
            )
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict) or row.get("id") is None:
                    continue
                fixture = normalize_match(row, series_id=series_id)
                all_rows[fixture.pandascore_match_id] = fixture
        return sorted(
            all_rows.values(),
            key=lambda item: item.scheduled_at or item.begin_at or datetime.max,
            reverse=True,
        )

    async def resolve_games(
        self,
        series_id: int,
        team_queries: list[str],
        *,
        game_number: int | None = None,
        scheduled_date: date | None = None,
        pandascore_match_id: int | None = None,
    ) -> ResolvedMatchGames:
        fixtures = await self.list_matches(series_id)
        matching = [fixture for fixture in fixtures if _teams_match(fixture, team_queries)]
        if pandascore_match_id is not None:
            matching = [
                fixture
                for fixture in matching
                if fixture.pandascore_match_id == pandascore_match_id
            ]
        if scheduled_date is not None:
            matching = [
                fixture
                for fixture in matching
                if (fixture.scheduled_at or fixture.begin_at)
                and (fixture.scheduled_at or fixture.begin_at).date() == scheduled_date
            ]
        if not matching:
            return ResolvedMatchGames(status="not_found")
        if len(matching) > 1:
            return ResolvedMatchGames(status="ambiguous", candidates=matching)
        fixture = matching[0]
        games = fixture.games
        if game_number is not None:
            games = [game for game in games if game.position == game_number]
        if not games:
            return ResolvedMatchGames(status="not_found", match=fixture)
        games = sorted(games, key=lambda game: (game.position is None, game.position or 0))
        coverage = [
            PandaCoverage(
                fixture_available=True,
                detailed_stats=None,
                valve_match_id_available=game.valve_match_id is not None,
            )
            for game in games
        ]
        return ResolvedMatchGames(
            status="resolved",
            match=fixture,
            games=games,
            coverage=coverage,
        )


def normalize_match(row: dict[str, Any], *, series_id: int | None = None) -> PandaMatchFixture:
    games = [
        normalize_game(game, pandascore_match_id=int(row["id"]))
        for game in row.get("games", [])
        if isinstance(game, dict) and game.get("id") is not None
    ]
    tournament = row.get("tournament")
    tournament_model = None
    if isinstance(tournament, dict) and tournament.get("id") is not None:
        tournament_model = {
            "pandascore_tournament_id": int(tournament["id"]),
            "pandascore_series_id": int(row.get("serie_id") or series_id),
            "name": str(tournament.get("name") or tournament["id"]),
            "begin_at": tournament.get("begin_at"),
            "end_at": tournament.get("end_at"),
            "tier": tournament.get("tier"),
            "region": tournament.get("region"),
        }
    return PandaMatchFixture(
        pandascore_match_id=int(row["id"]),
        pandascore_series_id=int(row.get("serie_id") or series_id),
        pandascore_tournament_id=_as_int(row.get("tournament_id")),
        name=str(row.get("name") or row["id"]),
        status=str(row.get("status") or "not_started"),
        scheduled_at=row.get("scheduled_at"),
        begin_at=row.get("begin_at"),
        end_at=row.get("end_at"),
        match_type=row.get("match_type"),
        number_of_games=_as_int(row.get("number_of_games")),
        opponents=row.get("opponents") if isinstance(row.get("opponents"), list) else [],
        results=row.get("results") if isinstance(row.get("results"), list) else [],
        streams=row.get("streams_list") if isinstance(row.get("streams_list"), list) else [],
        tournament=tournament_model,
        games=games,
    )


def normalize_game(row: dict[str, Any], *, pandascore_match_id: int) -> PandaGameReference:
    winner = row.get("winner") if isinstance(row.get("winner"), dict) else {}
    # PandaScore's games.match_id is the parent PandaScore match id, not Valve's id.
    return PandaGameReference(
        pandascore_game_id=int(row["id"]),
        pandascore_match_id=pandascore_match_id,
        position=_as_int(row.get("position")),
        status=row.get("status"),
        begin_at=row.get("begin_at"),
        end_at=row.get("end_at"),
        length_seconds=_as_int(row.get("length")),
        winner_team_id=_as_int(winner.get("id")),
        valve_match_id=_extract_valve_match_id(row),
    )


def _extract_valve_match_id(row: dict[str, Any]) -> int | None:
    for key in ("valve_match_id", "steam_match_id", "external_match_id"):
        value = row.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit() and int(value) > 0:
            return int(value)
    return None


def _teams_match(fixture: PandaMatchFixture, queries: Iterable[str]) -> bool:
    names: list[str] = []
    for opponent in fixture.opponents:
        team = opponent.get("opponent") if isinstance(opponent, dict) else None
        if isinstance(team, dict):
            for key in ("name", "acronym", "slug"):
                if team.get(key):
                    names.append(str(team[key]).casefold())
    normalized_queries = [query.strip().casefold() for query in queries]
    return all(
        any(query == name or query in name for name in names) for query in normalized_queries
    )


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
