"""Resolve PandaScore games to their canonical Valve match IDs."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

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
from app.vnext.providers.opendota.adapter import OpenDotaAdapter, OpenDotaProviderError
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
        """Resolve selected games through the batch evidence-loading path."""

        selected_match = replace(match, games=tuple(games))
        outcome = (await self.resolve_many_matches((selected_match,)))[0]
        if outcome.unavailable:
            raise OpenDotaProviderError("OpenDota resolution evidence is unavailable")
        return list(outcome.decisions or ())

    async def resolve_many_matches(
        self,
        matches: Sequence[NormalizedPandaMatch],
    ) -> list[MatchResolutionOutcome]:
        """Resolve many Matches while loading each OpenDota evidence set once."""

        selected_matches = tuple(matches)
        outcomes: list[MatchResolutionOutcome | None] = [None] * len(selected_matches)
        evidence_needed: list[int] = []
        for index, match in enumerate(selected_matches):
            if not match.games:
                outcomes[index] = MatchResolutionOutcome(decisions=())
            elif match.series_year is None:
                outcomes[index] = MatchResolutionOutcome(
                    decisions=tuple(
                        ResolutionDecision(
                            status="insufficient_signals",
                            warnings=("series year is unavailable",),
                        )
                        for _ in match.games
                    )
                )
            else:
                evidence_needed.append(index)

        if not evidence_needed:
            return _resolved_outcomes(outcomes)

        try:
            leagues_batch = await self.opendota.list_leagues()
        except OpenDotaProviderError:
            for index in evidence_needed:
                outcomes[index] = MatchResolutionOutcome(unavailable=True)
            return _resolved_outcomes(outcomes)

        leagues = [_league_signal(item) for item in leagues_batch.items]
        unique_league_by_match: dict[int, int] = {}
        for index in evidence_needed:
            match = selected_matches[index]
            matching = self.resolver.matching_leagues(
                match.series_name,
                match.series_year,
                leagues,
            )
            if len(matching) != 1:
                outcomes[index] = MatchResolutionOutcome(
                    decisions=self._resolve_match(match, leagues, {}, {})
                )
            else:
                unique_league_by_match[index] = matching[0].provider_id

        if not unique_league_by_match:
            return _resolved_outcomes(outcomes)

        try:
            teams_batch = await self.opendota.list_teams()
        except OpenDotaProviderError:
            for index in unique_league_by_match:
                outcomes[index] = MatchResolutionOutcome(unavailable=True)
            return _resolved_outcomes(outcomes)

        team_index = _team_signal_index([_team_signal(item) for item in teams_batch.items])
        league_matches_by_id = await self._load_league_matches(
            tuple(sorted(set(unique_league_by_match.values())))
        )
        for index, league_id in unique_league_by_match.items():
            league_matches = league_matches_by_id[league_id]
            if league_matches is None:
                outcomes[index] = MatchResolutionOutcome(unavailable=True)
                continue
            match = selected_matches[index]
            team_candidates = {
                normalize_text(team.name): list(team_index.get(normalize_text(team.name), ()))
                for team in match.summary.teams
            }
            outcomes[index] = MatchResolutionOutcome(
                decisions=self._resolve_match(
                    match,
                    leagues,
                    team_candidates,
                    {league_id: league_matches},
                )
            )
        return _resolved_outcomes(outcomes)

    async def _load_league_matches(
        self,
        league_ids: Sequence[int],
    ) -> dict[int, list[LeagueMatchSignal] | None]:
        """Load each unique league once, preserving per-league degradation."""

        results: dict[int, list[LeagueMatchSignal] | None] = {}
        for league_id in league_ids:
            try:
                batch = await self.opendota.list_league_matches(league_id)
            except OpenDotaProviderError:
                results[league_id] = None
                continue
            results[league_id] = [_league_match_signal(item, league_id) for item in batch.items]
        return results

    def _resolve_match(
        self,
        match: NormalizedPandaMatch,
        leagues: list[LeagueSignal],
        team_candidates: dict[str, list[TeamSignal]],
        league_matches: dict[int, list[LeagueMatchSignal]],
    ) -> tuple[ResolutionDecision, ...]:
        fixture_teams = tuple(
            TeamSignal(
                provider_id=provider_id,
                name=team.name,
                tag=team.acronym,
                fixture_id=provider_id,
            )
            for provider_id, team in match.teams_by_provider_id.items()
        )
        return tuple(
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
            for game in match.games
        )


@dataclass(frozen=True, slots=True)
class MatchResolutionOutcome:
    """Per-Match batch resolution result, including evidence degradation."""

    decisions: tuple[ResolutionDecision, ...] | None = None
    unavailable: bool = False


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


def _team_signal_index(
    teams: Sequence[TeamSignal],
) -> dict[str, tuple[TeamSignal, ...]]:
    indexed: dict[str, dict[int, TeamSignal]] = {}
    for team in teams:
        for value in (team.name, team.tag):
            key = normalize_text(value or "")
            if key:
                indexed.setdefault(key, {}).setdefault(team.provider_id, team)
    return {key: tuple(candidates.values()) for key, candidates in indexed.items()}


def _resolved_outcomes(
    outcomes: Sequence[MatchResolutionOutcome | None],
) -> list[MatchResolutionOutcome]:
    if any(outcome is None for outcome in outcomes):
        raise RuntimeError("every Match resolution outcome must be set")
    return [outcome for outcome in outcomes if outcome is not None]


def _extract_year(value: str) -> int | None:
    match = re.search(r"\b((?:19|20)\d{2})\b", value)
    return int(match.group(1)) if match else None


__all__ = ["MatchResolutionOutcome", "ValveMatchIdResolver"]
