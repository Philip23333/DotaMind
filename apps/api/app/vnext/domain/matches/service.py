"""Match search, cross-source resolution, and detail composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from app.vnext.domain.common.models import (
    CompetitionRef,
    Freshness,
    GameRef,
    MatchRef,
    Provenance,
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
    MatchResolutionService,
    ResolutionDecision,
)
from app.vnext.domain.matches.valve_match_id_resolver import ValveMatchIdResolver
from app.vnext.providers.opendota.adapter import OpenDotaAdapter, OpenDotaProviderError
from app.vnext.providers.opendota.models import OpenDotaMatchDetail
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter
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


@dataclass(frozen=True, slots=True)
class _KnownGame:
    match_ref: str
    game: NormalizedGame


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
        self.valve_match_id_resolver = ValveMatchIdResolver(opendota, resolver=resolver)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._matches: dict[str, _KnownMatch] = {}
        self._games: dict[str, _KnownGame] = {}

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
        target = self._known_target(match_ref=match_ref, game_ref=game_ref)
        if target is None:
            return _not_found_detail()
        known, target_games = target

        try:
            attempts = await self._resolve_games(known, games=target_games)
        except OpenDotaProviderError:
            return self._provider_unavailable_detail(known.normalized, target_games)

        public_games: list[GameDetail] = []
        detail_fetched_at: datetime | None = None
        for attempt in attempts:
            if attempt.game is None:
                continue
            if attempt.decision.status != "resolved":
                public_games.append(_fixture_game(attempt.game, attempt.decision))
                continue
            resolved_match_id = attempt.decision.resolved_provider_match_id
            if resolved_match_id is None:
                public_games.append(_fixture_game(attempt.game, attempt.decision))
                continue
            try:
                detail = await self.opendota.get_match_detail(resolved_match_id)
            except OpenDotaProviderError:
                public_games.append(_unavailable_game(attempt.game, attempt.decision))
                continue
            detail_fetched_at = detail.fetched_at
            public_games.append(
                _normalize_opendota_game(
                    known.normalized,
                    attempt.game,
                    attempt.decision,
                    detail.item,
                    detail.fetched_at,
                )
            )

        return self._compose_detail(
            known.normalized,
            attempts,
            public_games,
            detail_fetched_at=detail_fetched_at,
        )

    async def _resolve_games(
        self,
        known: _KnownMatch,
        *,
        games: tuple[NormalizedGame, ...] | None = None,
    ) -> list[_ResolutionAttempt]:
        selected_games = games if games is not None else known.normalized.games
        decisions = await self.valve_match_id_resolver.resolve_many(
            known.normalized,
            selected_games,
        )
        return [
            _ResolutionAttempt(decision=decision, game=game)
            for game, decision in zip(selected_games, decisions, strict=True)
        ]

    def _provider_unavailable_detail(
        self,
        normalized: NormalizedPandaMatch,
        games: tuple[NormalizedGame, ...],
    ) -> MatchDetail:
        warning = (
            "OpenDota provider data was unavailable during identity resolution; "
            "PandaScore series facts remain available and OpenDota detail is outside coverage"
        )
        decision = ResolutionDecision(status="insufficient_signals", warnings=(warning,))
        attempts = [_ResolutionAttempt(decision=decision, game=game) for game in games]
        public_games = [_fixture_game(game, decision) for game in games]
        return MatchDetail(
            status="detail_unavailable",
            match=normalized.summary,
            games=public_games,
            resolution=_aggregate_resolution(attempts),
            provenance=Provenance(
                sources=["pandascore"],
                freshness=normalized.summary.provenance.freshness,
                identity_status="unresolved",
                warnings=list(
                    dict.fromkeys([*normalized.summary.provenance.warnings, warning])
                ),
            ),
        )

    def _compose_detail(
        self,
        normalized: NormalizedPandaMatch,
        attempts: list[_ResolutionAttempt],
        public_games: list[GameDetail],
        *,
        detail_fetched_at: datetime | None,
    ) -> MatchDetail:
        resolution = _aggregate_resolution(attempts)
        available_count = sum(item.detail_status == "available" for item in public_games)
        resolved_count = sum(item.decision.status == "resolved" for item in attempts)
        if available_count:
            status = "available"
        elif resolved_count:
            status = "detail_unavailable"
        else:
            status = "unresolved"
        warnings = [*normalized.summary.provenance.warnings, *resolution.warnings]
        warnings.extend(
            warning
            for game in public_games
            for warning in game.provenance.warnings
        )
        if resolved_count and available_count < resolved_count:
            warnings.append(
                "OpenDota game detail is unavailable; PandaScore series facts remain available"
            )
        if not attempts:
            warnings.append("PandaScore did not provide any game fixture for resolution")
        sources = ["pandascore"]
        if available_count:
            sources.append("opendota")
        identity_status = (
            "inferred_cross_source"
            if resolved_count
            else "ambiguous"
            if resolution.status in {"ambiguous_league", "ambiguous_team", "ambiguous_match"}
            else "unresolved"
        )
        return MatchDetail(
            status=status,
            match=normalized.summary,
            games=public_games,
            resolution=resolution,
            provenance=Provenance(
                sources=sources,
                freshness=Freshness(
                    fetched_at=(
                        detail_fetched_at
                        or normalized.summary.provenance.freshness.fetched_at
                    ),
                    status=(
                        "fresh"
                        if detail_fetched_at
                        else normalized.summary.provenance.freshness.status
                    ),
                ),
                identity_status=identity_status,
                warnings=list(dict.fromkeys(warnings)),
            ),
        )

    def remember_fixture(
        self,
        row: PandaScoreMatch,
        normalized: NormalizedPandaMatch,
        fetched_at: datetime,
    ) -> None:
        """Cache a fixture already fetched by a Phase 2 search/list call."""

        self._remember(row, normalized, fetched_at)

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
            self._games[game.public.ref.value] = _KnownGame(
                match_ref=normalized.summary.ref.value,
                game=game,
            )

    def _known_target(
        self,
        *,
        match_ref: MatchRef | None,
        game_ref: GameRef | None,
    ) -> tuple[_KnownMatch, tuple[NormalizedGame, ...]] | None:
        ref_value = match_ref.value if match_ref else None
        if game_ref is not None:
            known_game = self._games.get(game_ref.value)
            if known_game is None:
                return None
            known = self._matches.get(known_game.match_ref)
            return (known, (known_game.game,)) if known is not None else None
        known = self._matches.get(ref_value) if ref_value else None
        return (known, known.normalized.games) if known is not None else None


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


def _not_found_detail() -> MatchDetail:
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


def _aggregate_resolution(attempts: list[_ResolutionAttempt]) -> ResolutionSummary:
    if not attempts:
        return ResolutionSummary(
            status="insufficient_signals",
            candidate_count=0,
            warnings=["no game was available for resolution"],
        )
    statuses = [item.decision.status for item in attempts]
    if all(status == "resolved" for status in statuses):
        status = "resolved"
    else:
        priority = (
            "ambiguous_match",
            "ambiguous_league",
            "ambiguous_team",
            "insufficient_signals",
            "league_not_found",
            "team_not_found",
            "not_found",
        )
        status = next((candidate for candidate in priority if candidate in statuses), statuses[0])
    decisions = [item.decision for item in attempts]
    signals = list(
        dict.fromkeys(signal for decision in decisions for signal in decision.signals)
    )
    evidence = [item for decision in decisions for item in decision.candidate_evidence]
    warnings = list(
        dict.fromkeys(warning for decision in decisions for warning in decision.warnings)
    )
    return ResolutionSummary(
        status=status,
        candidate_count=sum(decision.candidate_count for decision in decisions),
        signals=signals,
        candidate_evidence=evidence,
        start_time_delta_seconds=(
            evidence[0].start_time_delta_seconds if len(evidence) == 1 else None
        ),
        duration_delta_seconds=(
            evidence[0].duration_delta_seconds if len(evidence) == 1 else None
        ),
        winner_consistent=evidence[0].winner_consistent if len(evidence) == 1 else None,
        warnings=warnings,
    )


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


def _fixture_game(game: NormalizedGame, decision: ResolutionDecision) -> GameDetail:
    warning = list(game.public.provenance.warnings)
    warning.extend(decision.warnings)
    return game.public.model_copy(
        update={
            "resolution": _public_resolution(decision),
            "provenance": game.public.provenance.model_copy(
                update={"warnings": list(dict.fromkeys(warning))}
            ),
        }
    )


def _unavailable_game(game: NormalizedGame, decision: ResolutionDecision) -> GameDetail:
    warning = "OpenDota game detail is unavailable; PandaScore game facts remain available"
    public = _fixture_game(game, decision)
    return public.model_copy(
        update={
            "detail_status": "unavailable",
            "provenance": public.provenance.model_copy(
                update={
                    "warnings": list(dict.fromkeys([*public.provenance.warnings, warning]))
                }
            ),
        }
    )


def _normalize_opendota_game(
    normalized: NormalizedPandaMatch,
    game: NormalizedGame,
    decision: ResolutionDecision,
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
    winner = game.public.winner or _winner_from_detail(normalized, decision, detail)
    return GameDetail(
        ref=game.public.ref,
        position=game.public.position,
        status="finished",
        scheduled_at=game.public.scheduled_at,
        started_at=_from_epoch(detail.start_time) or game.public.started_at,
        ended_at=None,
        duration_seconds=detail.duration or game.public.duration_seconds,
        winner=winner,
        detail_status="available",
        resolution=_public_resolution(decision),
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


def _winner_from_detail(
    normalized: NormalizedPandaMatch,
    decision: ResolutionDecision,
    detail: OpenDotaMatchDetail,
) -> object:
    if detail.radiant_win is None:
        return None
    winning_side = detail.radiant_team if detail.radiant_win else detail.dire_team
    winning_open_dota_id = (
        winning_side.get("team_id") if isinstance(winning_side, dict) else None
    )
    if winning_open_dota_id is not None:
        for fixture_id, open_dota_id in decision.resolved_team_ids:
            if open_dota_id == winning_open_dota_id:
                team = normalized.teams_by_provider_id.get(fixture_id)
                if team is not None:
                    return team.ref
    winning_name = winning_side.get("name") if isinstance(winning_side, dict) else None
    if winning_name:
        normalized_name = normalize_text(str(winning_name))
        for team in normalized.teams_by_provider_id.values():
            if normalize_text(team.name) == normalized_name:
                return team.ref
    return None


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


def _epoch_seconds(value: datetime | None) -> int | None:
    return int(value.timestamp()) if value is not None else None


def _from_epoch(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value, tz=timezone.utc) if value is not None else None


def _duration_seconds(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds()))


def _as_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = ["MatchService"]
