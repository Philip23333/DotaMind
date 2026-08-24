"""Match search, cross-source resolution, and detail composition."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from app.vnext.domain.common.models import (
    CompetitionRef,
    Freshness,
    GameRef,
    MatchRef,
    Provenance,
    hash_ref,
    normalize_text,
)
from app.vnext.domain.competitions.service import CompetitionService
from app.vnext.domain.matches.models import (
    CompetitionSummary,
    DraftPick,
    GameDetail,
    MatchCandidate,
    MatchDetail,
    MatchSearchResult,
    MatchSummary,
    ResolutionSummary,
    ScoreboardRow,
    TimeScope,
)
from app.vnext.domain.matches.normalization import (
    NormalizedGame,
    NormalizedPandaMatch,
    normalize_panda_match,
)
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
    OpenDotaLeagueMatch,
    OpenDotaMatchDetail,
    OpenDotaTeam,
)
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter, PandaScoreHTTPError
from app.vnext.providers.pandascore.models import PandaScoreMatch


@dataclass(frozen=True, slots=True)
class _KnownMatch:
    provider_id: int
    provider_row: PandaScoreMatch
    normalized: NormalizedPandaMatch
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class _ResolutionAttempt:
    decision: ResolutionDecision
    game: NormalizedGame | None


class MatchService:
    """Own match search and provider composition below the tool layer."""

    def __init__(
        self,
        pandascore: PandaScoreAdapter,
        opendota: OpenDotaAdapter,
        *,
        competition_service: CompetitionService | None = None,
        resolver: MatchResolutionService | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.pandascore = pandascore
        self.opendota = opendota
        self.competition_service = competition_service
        self.resolver = resolver or MatchResolutionService()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._matches: dict[str, _KnownMatch] = {}
        self._games: dict[str, str] = {}

    async def search(
        self,
        *,
        query: str | None = None,
        teams: list[str] | None = None,
        competition: CompetitionRef | None = None,
        time_scope: TimeScope = "all",
        limit: int = 10,
    ) -> MatchSearchResult:
        normalized_teams = [item.strip() for item in (teams or []) if item.strip()]
        provider_series_id: int | None = None
        if competition is not None and self.competition_service is None:
            return _not_found_search(
                query=query,
                teams=normalized_teams,
                warning="competition references require the competition capability",
            )
        known_competition = (
            self.competition_service.get_known(competition) if competition is not None else None
        )
        if competition is not None and known_competition is None:
            return _not_found_search(
                query=query,
                teams=normalized_teams,
                warning="competition reference is not known to this in-memory runtime",
            )
        if known_competition is not None and self.competition_service is not None:
            provider_series_id = self.competition_service.provider_id_for(known_competition.ref)
        provider_query = None if normalized_teams else query
        batch = await self.pandascore.list_matches(
            scope=time_scope,
            series_id=provider_series_id,
            query=provider_query,
            limit=limit,
        )
        candidates: list[MatchCandidate] = []
        seen: set[str] = set()
        for row in batch.items:
            normalized = normalize_panda_match(
                row,
                fetched_at=batch.fetched_at,
                competition_ref=known_competition.ref if known_competition else None,
                competition_name=known_competition.name if known_competition else None,
                competition_year=known_competition.year if known_competition else None,
            )
            if normalized.summary.ref.value in seen:
                continue
            if known_competition is not None:
                requested_competition = CompetitionSummary(
                    ref=known_competition.ref,
                    name=known_competition.name,
                    year=known_competition.year,
                )
                if normalized.summary.competition != requested_competition:
                    continue
            if not _match_query(normalized.summary, query):
                continue
            if not _match_teams(normalized.summary, normalized_teams):
                continue
            seen.add(normalized.summary.ref.value)
            candidates.append(MatchCandidate.model_validate(normalized.summary.model_dump()))
            self._remember(row, normalized, batch.fetched_at)
        reverse = time_scope in {"recent", "all"}
        candidates.sort(key=_schedule_key, reverse=reverse)
        total = len(candidates)
        candidates = candidates[: max(1, limit)]
        status = "not_found" if total == 0 else "unique" if total == 1 else "ambiguous"
        return MatchSearchResult(
            status=status,
            query=query.strip() if query else None,
            teams=normalized_teams,
            candidate_count=total,
            candidates=candidates,
            provenance=Provenance(
                sources=["pandascore"],
                freshness=Freshness(fetched_at=batch.fetched_at, status="fresh"),
                identity_status=(
                    "not_found" if total == 0 else "ambiguous" if total > 1 else "native"
                ),
                warnings=[],
            ),
        )

    async def get_detail(
        self,
        *,
        match_ref: MatchRef | None = None,
        game_ref: GameRef | None = None,
    ) -> MatchDetail:
        known = self._known_match(match_ref=match_ref, game_ref=game_ref)
        if known is None:
            return MatchDetail(
                status="not_found",
                match=None,
                games=[],
                resolution=ResolutionSummary(
                    status="not_found",
                    candidate_count=0,
                    warnings=["match reference is not known to this in-memory runtime"],
                ),
                provenance=Provenance(
                    sources=["pandascore"],
                    freshness=Freshness(status="unknown"),
                    identity_status="not_found",
                    warnings=["match references are runtime-scoped and are not persisted"],
                ),
            )

        pandascore_warning: str | None = None
        try:
            refreshed = await self.pandascore.get_match(known.provider_id)
        except PandaScoreHTTPError as exc:
            if exc.status_code != 404:
                raise
            pandascore_warning = (
                "PandaScore match detail is unavailable; cached PandaScore series facts "
                "were used for cross-source resolution"
            )
        else:
            normalized = normalize_panda_match(
                refreshed.item,
                fetched_at=refreshed.fetched_at,
                competition_ref=known.normalized.summary.competition.ref
                if known.normalized.summary.competition
                else None,
                competition_name=known.normalized.competition_name,
                competition_year=known.normalized.competition_year,
            )
            self._remember(refreshed.item, normalized, refreshed.fetched_at)
            known = _KnownMatch(
                provider_id=refreshed.item.provider_id,
                provider_row=refreshed.item,
                normalized=normalized,
                fetched_at=refreshed.fetched_at,
            )

        try:
            attempts = await self._resolve_games(known)
        except OpenDotaProviderError:
            return self._provider_unavailable_detail(
                known.normalized,
                extra_warning=pandascore_warning,
            )
        combined = _combine_attempts(attempts)
        if combined.decision.status != "resolved" or combined.game is None:
            return self._unresolved_detail(
                known.normalized,
                combined.decision,
                extra_warning=pandascore_warning,
            )

        try:
            detail = await self.opendota.get_match_detail(
                combined.decision.resolved_provider_match_id or 0
            )
        except OpenDotaProviderError:
            return self._detail_unavailable(
                known.normalized,
                combined.decision,
                extra_warning=pandascore_warning,
            )

        return self._available_detail(
            known.normalized,
            combined.game,
            combined.decision,
            detail.item,
            detail.fetched_at,
            extra_warning=pandascore_warning,
        )

    async def _resolve_games(self, known: _KnownMatch) -> list[_ResolutionAttempt]:
        competition = known.normalized.summary.competition
        if competition is None or competition.year is None:
            return [
                _ResolutionAttempt(
                    decision=ResolutionDecision(
                        status="insufficient_signals",
                        warnings=("competition year is unavailable",),
                    ),
                    game=None,
                )
            ]
        leagues_batch = await self.opendota.list_leagues()
        leagues = [
            LeagueSignal(
                provider_id=league.provider_id,
                name=league.name,
                year=_extract_year(league.name),
            )
            for league in leagues_batch.items
        ]
        matching_leagues = self.resolver.matching_leagues(
            known.normalized.competition_name,
            known.normalized.competition_year,
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
            for team in known.normalized.summary.teams
        }
        fixture_teams = tuple(
            TeamSignal(
                provider_id=provider_id,
                name=team.name,
                tag=team.acronym,
                fixture_id=provider_id,
            )
            for provider_id, team in known.normalized.teams_by_provider_id.items()
        )
        games = list(known.normalized.games)
        if not games:
            games = [
                NormalizedGame(
                    provider_id=known.provider_id,
                    public=GameDetail(
                        ref=GameRef(
                            value=hash_ref("game", "pandascore", known.provider_id, "series")
                        ),
                        status=known.normalized.summary.status,
                        started_at=known.normalized.summary.started_at,
                        scheduled_at=known.normalized.summary.scheduled_at,
                        ended_at=known.normalized.summary.ended_at,
                        provenance=known.normalized.summary.provenance,
                    ),
                    start_time=_epoch_seconds(
                        known.normalized.summary.started_at or known.normalized.summary.scheduled_at
                    ),
                    duration_seconds=_duration_seconds(
                        known.normalized.summary.started_at,
                        known.normalized.summary.ended_at,
                    ),
                    winner_provider_id=known.normalized.winner_provider_id,
                )
            ]
        attempts: list[_ResolutionAttempt] = []
        for game in games:
            fixture = MatchSignal(
                provider_id=game.provider_id,
                competition_name=known.normalized.competition_name,
                competition_year=known.normalized.competition_year,
                teams=fixture_teams,
                start_time=game.start_time,
                duration_seconds=game.duration_seconds,
                winner_team_id=game.winner_provider_id,
            )
            decision = self.resolver.resolve(
                fixture,
                leagues,
                team_candidates,
                league_matches,
            )
            attempts.append(_ResolutionAttempt(decision=decision, game=game))
        return attempts

    def _available_detail(
        self,
        normalized: NormalizedPandaMatch,
        game: NormalizedGame,
        decision: ResolutionDecision,
        detail: OpenDotaMatchDetail,
        fetched_at: datetime,
        *,
        extra_warning: str | None = None,
    ) -> MatchDetail:
        public_game = _normalize_opendota_game(
            normalized,
            game,
            detail,
            fetched_at,
        )
        games = [
            public_game if item.provider_id == game.provider_id else item.public
            for item in normalized.games
        ]
        if not normalized.games:
            games = [public_game]
        warnings = list(normalized.summary.provenance.warnings)
        warnings.extend(public_game.provenance.warnings)
        if extra_warning:
            warnings.append(extra_warning)
        return MatchDetail(
            status="available",
            match=normalized.summary,
            games=games,
            resolution=_public_resolution(decision),
            provenance=Provenance(
                sources=["pandascore", "opendota"],
                freshness=Freshness(fetched_at=fetched_at, status="fresh"),
                identity_status="inferred_cross_source",
                warnings=list(dict.fromkeys(warnings)),
            ),
        )

    def _detail_unavailable(
        self,
        normalized: NormalizedPandaMatch,
        decision: ResolutionDecision,
        *,
        extra_warning: str | None = None,
    ) -> MatchDetail:
        warning = "OpenDota match detail is unavailable; PandaScore series facts remain available"
        games = [item.public for item in normalized.games]
        warnings = [*normalized.summary.provenance.warnings, warning]
        if extra_warning:
            warnings.append(extra_warning)
        return MatchDetail(
            status="detail_unavailable",
            match=normalized.summary,
            games=games,
            resolution=_public_resolution(decision),
            provenance=Provenance(
                sources=["pandascore"],
                freshness=normalized.summary.provenance.freshness,
                identity_status="inferred_cross_source",
                warnings=list(dict.fromkeys(warnings)),
            ),
        )

    def _provider_unavailable_detail(
        self,
        normalized: NormalizedPandaMatch,
        *,
        extra_warning: str | None = None,
    ) -> MatchDetail:
        warning = (
            "OpenDota provider data was unavailable during identity resolution; "
            "PandaScore series facts remain available and OpenDota detail is outside coverage"
        )
        warnings = [*normalized.summary.provenance.warnings, warning]
        if extra_warning:
            warnings.append(extra_warning)
        return MatchDetail(
            status="detail_unavailable",
            match=normalized.summary,
            games=[item.public for item in normalized.games],
            resolution=ResolutionSummary(
                status="insufficient_signals",
                candidate_count=0,
                warnings=[warning],
            ),
            provenance=Provenance(
                sources=["pandascore"],
                freshness=normalized.summary.provenance.freshness,
                identity_status="unresolved",
                warnings=list(dict.fromkeys(warnings)),
            ),
        )

    def _unresolved_detail(
        self,
        normalized: NormalizedPandaMatch,
        decision: ResolutionDecision,
        *,
        extra_warning: str | None = None,
    ) -> MatchDetail:
        warning = "OpenDota game-level detail is unavailable until cross-source identity resolves"
        games = [item.public for item in normalized.games]
        warnings = [*normalized.summary.provenance.warnings, warning]
        if extra_warning:
            warnings.append(extra_warning)
        return MatchDetail(
            status="unresolved",
            match=normalized.summary,
            games=games,
            resolution=_public_resolution(decision),
            provenance=Provenance(
                sources=["pandascore"],
                freshness=normalized.summary.provenance.freshness,
                identity_status=(
                    "ambiguous"
                    if decision.status in {"ambiguous_league", "ambiguous_team", "ambiguous_match"}
                    else "unresolved"
                ),
                warnings=list(dict.fromkeys(warnings)),
            ),
        )

    def _remember(
        self,
        row: PandaScoreMatch,
        normalized: NormalizedPandaMatch,
        fetched_at: datetime,
    ) -> None:
        self._matches[normalized.summary.ref.value] = _KnownMatch(
            provider_id=row.provider_id,
            provider_row=row,
            normalized=normalized,
            fetched_at=fetched_at,
        )
        for game in normalized.games:
            self._games[game.public.ref.value] = normalized.summary.ref.value

    def _known_match(
        self,
        *,
        match_ref: MatchRef | None,
        game_ref: GameRef | None,
    ) -> _KnownMatch | None:
        ref_value = match_ref.value if match_ref else None
        if game_ref is not None:
            ref_value = self._games.get(game_ref.value)
        return self._matches.get(ref_value) if ref_value else None


def _not_found_search(
    *,
    query: str | None,
    teams: list[str],
    warning: str,
) -> MatchSearchResult:
    return MatchSearchResult(
        status="not_found",
        query=query.strip() if query and query.strip() else None,
        teams=teams,
        candidate_count=0,
        candidates=[],
        provenance=Provenance(
            sources=["pandascore"],
            freshness=Freshness(status="unknown"),
            identity_status="not_found",
            warnings=[warning],
        ),
    )


def _combine_attempts(attempts: list[_ResolutionAttempt]) -> _ResolutionAttempt:
    if not attempts:
        return _ResolutionAttempt(
            decision=ResolutionDecision(status="insufficient_signals"),
            game=None,
        )
    resolved = [item for item in attempts if item.decision.status == "resolved"]
    ambiguous = [item for item in attempts if item.decision.status == "ambiguous_match"]
    resolved_ids = {
        item.decision.resolved_provider_match_id
        for item in resolved
        if item.decision.resolved_provider_match_id
    }
    if ambiguous or len(resolved_ids) > 1:
        evidence = tuple(
            evidence
            for item in [*resolved, *ambiguous]
            for evidence in item.decision.candidate_evidence
        )
        return _ResolutionAttempt(
            decision=ResolutionDecision(
                status="ambiguous_match",
                candidate_count=len(evidence) or len(resolved_ids),
                signals=tuple(
                    dict.fromkeys(
                        signal
                        for item in [*resolved, *ambiguous]
                        for signal in item.decision.signals
                    )
                ),
                candidate_evidence=evidence,
                warnings=("multiple credible game mappings remain ambiguous",),
            ),
            game=None,
        )
    if len(resolved) == 1:
        return resolved[0]
    priority = (
        "ambiguous_league",
        "ambiguous_team",
        "insufficient_signals",
        "league_not_found",
        "team_not_found",
        "not_found",
    )
    for status in priority:
        for attempt in attempts:
            if attempt.decision.status == status:
                return attempt
    return attempts[0]


def _public_resolution(decision: ResolutionDecision) -> ResolutionSummary:
    return ResolutionSummary(
        status=decision.status,
        candidate_count=decision.candidate_count,
        signals=list(decision.signals),
        candidate_evidence=list(decision.candidate_evidence),
        start_time_delta_seconds=(
            decision.candidate_evidence[0].start_time_delta_seconds
            if decision.candidate_evidence
            else None
        ),
        duration_delta_seconds=(
            decision.candidate_evidence[0].duration_delta_seconds
            if decision.candidate_evidence
            else None
        ),
        winner_consistent=(
            decision.candidate_evidence[0].winner_consistent
            if decision.candidate_evidence
            else None
        ),
        warnings=list(decision.warnings),
    )


def _normalize_opendota_game(
    normalized: NormalizedPandaMatch,
    game: NormalizedGame,
    detail: OpenDotaMatchDetail,
    fetched_at: datetime,
) -> GameDetail:
    warnings: list[str] = []
    if not detail.players:
        warnings.append("OpenDota did not provide parsed player rows")
    if not detail.picks_bans:
        warnings.append("OpenDota did not provide draft rows")
    if detail.version is None:
        warnings.append("OpenDota parse version is unavailable")
    draft = [
        DraftPick(
            order=item.get("order"),
            action=(
                "pick"
                if item.get("is_pick") is True
                else "ban"
                if item.get("is_pick") is False
                else "unknown"
            ),
            side=(
                "radiant"
                if item.get("team") == 0
                else "dire"
                if item.get("team") == 1
                else "unknown"
            ),
        )
        for item in detail.picks_bans
        if isinstance(item, dict)
    ]
    scoreboard = [
        ScoreboardRow(
            player_name=item.get("name") or item.get("personaname"),
            side=(
                "radiant"
                if item.get("isRadiant") is True
                else "dire"
                if item.get("isRadiant") is False
                else "unknown"
            ),
            kills=_as_int(item.get("kills")),
            deaths=_as_int(item.get("deaths")),
            assists=_as_int(item.get("assists")),
            last_hits=_as_int(item.get("last_hits")),
            gold_per_min=_as_int(item.get("gold_per_min")),
            xp_per_min=_as_int(item.get("xp_per_min")),
        )
        for item in detail.players
        if isinstance(item, dict)
    ]
    return GameDetail(
        ref=game.public.ref,
        position=game.public.position,
        status="finished",
        scheduled_at=game.public.scheduled_at,
        started_at=_from_epoch(detail.start_time) or game.public.started_at,
        ended_at=None,
        duration_seconds=detail.duration or game.public.duration_seconds,
        winner=normalized.summary.result.winner if normalized.summary.result else None,
        detail_status="available",
        radiant_win=detail.radiant_win,
        radiant_score=detail.radiant_score,
        dire_score=detail.dire_score,
        draft=draft,
        scoreboard=scoreboard,
        coverage=["opendota_match_detail", "pandascore_fixture"],
        provenance=Provenance(
            sources=["pandascore", "opendota"],
            freshness=Freshness(fetched_at=fetched_at, status="fresh"),
            identity_status="inferred_cross_source",
            warnings=warnings,
        ),
    )


def _match_query(summary: MatchSummary, query: str | None) -> bool:
    if not query:
        return True
    tokens = [
        token
        for token in normalize_text(query).split()
        if token not in {"and", "vs", "v", "versus", "against"}
    ]
    values = [team.name for team in summary.teams]
    values.append(summary.name)
    if summary.competition is not None:
        values.append(summary.competition.name)
    haystack = normalize_text(" ".join(values))
    return all(token in haystack for token in tokens)


def _match_teams(summary: MatchSummary, queries: list[str]) -> bool:
    if not queries:
        return True
    names = [normalize_text(team.name) for team in summary.teams]
    return all(
        any(normalize_text(query) == name or normalize_text(query) in name for name in names)
        for query in queries
    )


def _schedule_key(match: MatchSummary) -> datetime:
    return match.scheduled_at or match.started_at or datetime.max.replace(tzinfo=timezone.utc)


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


def _epoch_seconds(value: datetime | None) -> int | None:
    return int(value.timestamp()) if value is not None else None


def _from_epoch(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value, tz=timezone.utc) if value is not None else None


def _duration_seconds(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds()))


def _extract_year(value: str) -> int | None:
    match = re.search(r"\b((?:19|20)\d{2})\b", value)
    return int(match.group(1)) if match else None


def _as_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = ["MatchService"]
