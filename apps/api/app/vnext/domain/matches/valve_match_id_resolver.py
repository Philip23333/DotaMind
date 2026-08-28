"""Resolve PandaScore games to their canonical Valve match IDs."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.vnext.domain.common.models import normalize_text
from app.vnext.domain.matches.normalization import NormalizedGame, NormalizedPandaMatch
from app.vnext.domain.matches.resolution import (
    LeagueMatchSignal,
    LeagueSignal,
    MatchResolutionService,
    MatchSignal,
    ResolutionDecision,
    TeamSignal,
)
from app.vnext.providers.opendota.adapter import OpenDotaAdapter
from app.vnext.providers.opendota.models import (
    OpenDotaLeague,
    OpenDotaLeagueMatch,
    OpenDotaTeam,
)


class ValveMatchIdResolver:
    """Coordinate cross-source match identity resolution below the tool layer."""

    def __init__(
        self,
        opendota: OpenDotaAdapter,
        *,
        resolver: MatchResolutionService | None = None,
    ) -> None:
        self.opendota = opendota
        self.resolver = resolver or MatchResolutionService()

    async def resolve(
        self,
        match: NormalizedPandaMatch,
        game: NormalizedGame,
    ) -> ResolutionDecision:
        """Resolve one game while retaining the single-game convenience API."""

        return (await self.resolve_many(match, (game,)))[0]

    async def resolve_many(
        self,
        match: NormalizedPandaMatch,
        games: Sequence[NormalizedGame],
    ) -> list[ResolutionDecision]:
        """Resolve games after loading shared OpenDota resolution data once."""

        selected_games = tuple(games)
        series = match.summary.series
        if series is None or series.year is None:
            return [
                ResolutionDecision(
                    status="insufficient_signals",
                    warnings=("series year is unavailable",),
                )
                for _ in selected_games
            ]

        leagues_batch = await self.opendota.list_leagues()
        leagues = [_league_signal(item) for item in leagues_batch.items]
        matching_leagues = self.resolver.matching_leagues(
            match.series_name,
            match.series_year,
            leagues,
        )
        league_matches: dict[int, list[LeagueMatchSignal]] = {}
        if len(matching_leagues) == 1:
            league_id = matching_leagues[0].provider_id
            match_batch = await self.opendota.list_league_matches(league_id)
            league_matches[league_id] = [
                _league_match_signal(item, league_id) for item in match_batch.items
            ]

        teams_batch = await self.opendota.list_teams()
        open_teams = [_team_signal(item) for item in teams_batch.items]
        team_candidates = {
            normalize_text(team.name): [
                candidate
                for candidate in open_teams
                if _same_team_name(team.name, candidate.name, candidate.tag)
            ]
            for team in match.summary.teams
        }
        fixture_teams = tuple(
            TeamSignal(
                provider_id=provider_id,
                name=team.name,
                tag=team.acronym,
                fixture_id=provider_id,
            )
            for provider_id, team in match.teams_by_provider_id.items()
        )
        return [
            self.resolver.resolve(
                MatchSignal(
                    provider_id=game.provider_id,
                    series_name=match.series_name,
                    series_year=match.series_year,
                    teams=fixture_teams,
                    start_time=game.start_time,
                    duration_seconds=game.duration_seconds,
                    winner_team_id=game.winner_provider_id,
                ),
                leagues,
                team_candidates,
                league_matches,
            )
            for game in selected_games
        ]


def _league_signal(item: OpenDotaLeague) -> LeagueSignal:
    return LeagueSignal(
        provider_id=item.provider_id,
        name=item.name,
        year=_extract_year(item.name),
    )


def _league_match_signal(item: OpenDotaLeagueMatch, league_id: int) -> LeagueMatchSignal:
    return LeagueMatchSignal(
        provider_id=item.provider_match_id,
        league_id=item.league_id or league_id,
        start_time=item.start_time,
        duration_seconds=item.duration,
        radiant_team_id=item.radiant_team_id,
        dire_team_id=item.dire_team_id,
        radiant_win=item.radiant_win,
    )


def _team_signal(item: OpenDotaTeam) -> TeamSignal:
    return TeamSignal(
        provider_id=item.provider_id,
        name=item.name or item.tag or str(item.provider_id),
        tag=item.tag,
    )


def _same_team_name(query: str, name: str, tag: str | None) -> bool:
    normalized_query = normalize_text(query)
    return normalized_query in {normalize_text(name), normalize_text(tag or "")}


def _extract_year(value: str) -> int | None:
    match = re.search(r"\b((?:19|20)\d{2})\b", value)
    return int(match.group(1)) if match else None


__all__ = ["ValveMatchIdResolver"]
