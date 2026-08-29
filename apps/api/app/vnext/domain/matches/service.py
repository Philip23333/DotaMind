"""Match search, cross-source resolution, and detail composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from app.vnext.domain.common.models import (
    Freshness,
    GameRef,
    MatchRef,
    Provenance,
    SeriesRef,
    normalize_text,
)
from app.vnext.domain.matches.models import (
    DraftPick,
    GameDetail,
    MatchCandidate,
    MatchDetail,
    MatchSearchResult,
    MatchSummary,
    ResolutionSummary,
    ScoreboardRow,
    SeriesSummary,
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
from app.vnext.domain.series.models import Series
from app.vnext.domain.series.service import SeriesService, series_display_name
from app.vnext.domain.source import SourceLocator, SourceLocatorError
from app.vnext.domain.team_player_index import TeamPlayerRefIndex
from app.vnext.providers.opendota.adapter import OpenDotaAdapter, OpenDotaProviderError
from app.vnext.providers.opendota.models import OpenDotaMatchDetail
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter
from app.vnext.providers.pandascore.locator import PandaScoreLocatorIndex
from app.vnext.providers.pandascore.models import PandaScoreMatch, PandaScoreTeam

_TEAM_SEARCH_LIMIT = 20
_TEAM_MATCH_PAGE_SIZE = 100
_TEAM_MATCH_MAX_PAGES = 5


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
        series_service: SeriesService | None = None,
        locator_index: PandaScoreLocatorIndex | None = None,
        resolver: MatchResolutionService | None = None,
        team_player_index: TeamPlayerRefIndex | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.pandascore = pandascore
        self.opendota = opendota
        self.series_service = series_service
        self.locator_index = locator_index or PandaScoreLocatorIndex()
        self.team_player_index = team_player_index or TeamPlayerRefIndex()
        self.valve_match_id_resolver = ValveMatchIdResolver(opendota, resolver=resolver)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._matches: dict[str, _KnownMatch] = {}
        self._games: dict[str, _KnownGame] = {}

    async def search(
        self,
        *,
        query: str | None = None,
        teams: list[str] | None = None,
        series: SeriesRef | None = None,
        time_scope: TimeScope = "all",
        limit: int = 10,
    ) -> MatchSearchResult:
        normalized_teams = [item.strip() for item in (teams or []) if item.strip()]
        provider_series_id: int | None = None
        if series is not None and self.series_service is None:
            return _not_found_search(
                query=query,
                teams=normalized_teams,
                warning="series references require the series capability",
            )
        known_series = (
            self.series_service.get_known(series) if series is not None else None
        )
        if series is not None and known_series is None:
            return _not_found_search(
                query=query,
                teams=normalized_teams,
                warning="series reference is not known to this in-memory runtime",
            )
        if known_series is not None and self.series_service is not None:
            provider_series_id = self.series_service.provider_id_for(known_series.ref)
        if normalized_teams:
            return await self._search_by_teams(
                query=query,
                teams=normalized_teams,
                known_series=known_series,
                provider_series_id=provider_series_id,
                time_scope=time_scope,
                limit=limit,
            )
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
            normalized = _normalize_search_match(
                row,
                fetched_at=batch.fetched_at,
                series_ref=known_series.ref if known_series else None,
                series_name=known_series.name if known_series else None,
                series_year=known_series.year if known_series else None,
            )
            if normalized.summary.ref.value in seen:
                continue
            if known_series is not None:
                requested_series = SeriesSummary(
                    ref=known_series.ref,
                    name=known_series.name,
                    year=known_series.year,
                )
                if normalized.summary.series != requested_series:
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

    async def _search_by_teams(
        self,
        *,
        query: str | None,
        teams: list[str],
        known_series: Series | None,
        provider_series_id: int | None,
        time_scope: TimeScope,
        limit: int,
    ) -> MatchSearchResult:
        resolved: list[PandaScoreTeam] = []
        warnings: list[str] = []
        for team_query in teams:
            batch = await self.pandascore.search_teams(
                query=team_query,
                limit=_TEAM_SEARCH_LIMIT,
            )
            candidates = _exact_team_matches(team_query, batch.items)
            if len(candidates) == 1:
                resolved.append(candidates[0])
            elif not candidates:
                warnings.append(
                    f"no unique PandaScore team matched {team_query!r} by exact normalized "
                    "name, acronym, or slug"
                )
            else:
                warnings.append(
                    f"multiple PandaScore teams matched {team_query!r} by exact normalized "
                    "name, acronym, or slug; provider identity was not guessed"
                )

        if len(resolved) != len(teams):
            return _not_found_search(query=query, teams=teams, warning=warnings)
        provider_team_ids = {team.provider_id for team in resolved}
        if len(provider_team_ids) != len(resolved):
            return _not_found_search(
                query=query,
                teams=teams,
                warning=[
                    "team queries did not resolve to two distinct provider teams; "
                    "provider identity was not guessed"
                ],
            )

        requested_limit = max(1, limit)
        matches: list[MatchSummary] = []
        seen: set[str] = set()
        page_warnings: list[str] = []
        fetched_at: datetime | None = None
        for page_number in range(1, _TEAM_MATCH_MAX_PAGES + 1):
            batch = await self.pandascore.list_team_matches(
                resolved[0].provider_id,
                page_number=page_number,
                page_size=_TEAM_MATCH_PAGE_SIZE,
                sort=_team_match_sort(time_scope),
                query=None,
                series_id=provider_series_id,
            )
            fetched_at = (
                batch.fetched_at
                if fetched_at is None
                else max(fetched_at, batch.fetched_at)
            )
            for row in batch.items:
                if not _has_provider_teams(row, provider_team_ids):
                    continue
                if (
                    provider_series_id is not None
                    and _provider_series_id(row) != provider_series_id
                ):
                    continue
                normalized = _normalize_search_match(
                    row,
                    fetched_at=batch.fetched_at,
                    series_ref=known_series.ref if known_series else None,
                    series_name=known_series.name if known_series else None,
                    series_year=known_series.year if known_series else None,
                )
                if not _time_scope_matches(normalized.summary, time_scope):
                    continue
                if not _match_query(normalized.summary, query):
                    continue
                if normalized.summary.ref.value in seen:
                    continue
                seen.add(normalized.summary.ref.value)
                matches.append(normalized.summary)
                page_warnings.extend(normalized.summary.provenance.warnings)
                self._remember(row, normalized, batch.fetched_at)

            if len(matches) >= requested_limit:
                break
            if batch.has_more is False:
                break
            if page_number == _TEAM_MATCH_MAX_PAGES:
                page_warnings.append(
                    "team match discovery was bounded at 5 pages; additional provider pages "
                    "may exist, so results are truncated"
                )

        reverse = time_scope in {"recent", "all"}
        matches.sort(key=_schedule_key, reverse=reverse)
        matches = matches[:requested_limit]
        total = len(matches)
        return MatchSearchResult(
            status="not_found" if total == 0 else "unique" if total == 1 else "ambiguous",
            query=query.strip() if query else None,
            teams=teams,
            candidate_count=total,
            candidates=[MatchCandidate.model_validate(item.model_dump()) for item in matches],
            provenance=Provenance(
                sources=["pandascore"],
                freshness=Freshness(fetched_at=fetched_at, status="fresh"),
                identity_status=(
                    "not_found" if total == 0 else "ambiguous" if total > 1 else "native"
                ),
                warnings=list(dict.fromkeys(page_warnings)),
            ),
        )

    async def get_detail(
        self,
        *,
        locator: SourceLocator | None = None,
        match_ref: MatchRef | None = None,
        game_ref: GameRef | None = None,
    ) -> MatchDetail:
        target = (
            await self._known_target_for_locator(locator)
            if locator is not None
            else self._known_target(match_ref=match_ref, game_ref=game_ref)
        )
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

    async def _known_target_for_locator(
        self,
        locator: SourceLocator,
    ) -> tuple[_KnownMatch, tuple[NormalizedGame, ...]]:
        resolved = self.locator_index.resolve(locator)
        if resolved.kind == "match":
            provider_match_id = resolved.provider_id
            requested_game_id: int | None = None
        elif resolved.kind == "game":
            provider_match_id = resolved.parent_match_provider_id
            requested_game_id = resolved.provider_id
            if provider_match_id is None:
                raise SourceLocatorError(
                    "game source locator is not linked to a PandaScore match",
                    details={"source": locator.source, "kind": locator.kind},
                )
        else:
            raise SourceLocatorError(
                "source locator cannot be used for match detail",
                details={"source": locator.source, "kind": locator.kind},
            )

        provider_match = await self.pandascore.get_match(provider_match_id)
        normalized = _normalize_search_match(
            provider_match.item,
            fetched_at=provider_match.fetched_at,
        )
        self._remember(provider_match.item, normalized, provider_match.fetched_at)
        known = self._matches[normalized.summary.ref.value]
        if requested_game_id is None:
            return known, known.normalized.games
        games = tuple(
            game for game in known.normalized.games if game.provider_id == requested_game_id
        )
        if games:
            return known, games
        raise SourceLocatorError(
            "game source locator is not present in its PandaScore match",
            details={"source": locator.source, "kind": locator.kind},
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
        for opponent in row.opponents:
            self.team_player_index.remember_team(opponent.opponent.provider_id)
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
    warning: str | list[str],
) -> MatchSearchResult:
    warnings = [warning] if isinstance(warning, str) else warning
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
            warnings=list(dict.fromkeys(warnings)),
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
            "valve_match_id": decision.resolved_provider_match_id,
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
        valve_match_id=decision.resolved_provider_match_id,
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
    if summary.series is not None:
        values.append(summary.series.name)
    haystack = normalize_text(" ".join(values))
    return all(token in haystack for token in tokens)


def _normalize_search_match(
    row: PandaScoreMatch,
    *,
    fetched_at: datetime,
    series_ref: SeriesRef | None = None,
    series_name: str | None = None,
    series_year: int | None = None,
) -> NormalizedPandaMatch:
    normalized = normalize_panda_match(
        row,
        fetched_at=fetched_at,
        series_ref=series_ref,
        series_name=series_name,
        series_year=series_year,
    )
    if series_name is not None or normalized.summary.series is None:
        return normalized
    series = row.series
    league_name = (
        row.league.name
        if row.league and row.league.name
        else series.league.name
        if series and series.league and series.league.name
        else None
    )
    if not league_name and not series:
        return normalized
    display_name = series_display_name(
        league_name=league_name,
        series_name=series.name if series else None,
        series_full_name=series.full_name if series else None,
        year=normalized.series_year,
    )
    if display_name == normalized.summary.series.name:
        return normalized
    series_summary = normalized.summary.series.model_copy(update={"name": display_name})
    summary = normalized.summary.model_copy(update={"series": series_summary})
    return replace(
        normalized,
        summary=summary,
        series_name=display_name,
    )


def _exact_team_matches(query: str, candidates: list[PandaScoreTeam]) -> list[PandaScoreTeam]:
    needle = normalize_text(query)
    matches: dict[int, PandaScoreTeam] = {}
    for candidate in candidates:
        values = (candidate.name, candidate.acronym, candidate.slug)
        if any(value and normalize_text(value) == needle for value in values):
            matches[candidate.provider_id] = candidate
    return list(matches.values())


def _has_provider_teams(row: PandaScoreMatch, provider_team_ids: set[int]) -> bool:
    row_team_ids = {item.opponent.provider_id for item in row.opponents}
    return provider_team_ids.issubset(row_team_ids)


def _provider_series_id(row: PandaScoreMatch) -> int | None:
    return row.series_id or (row.series.provider_id if row.series else None)


def _time_scope_matches(summary: MatchSummary, time_scope: TimeScope) -> bool:
    if time_scope == "recent":
        return summary.status == "finished"
    if time_scope == "upcoming":
        return summary.status == "scheduled"
    if time_scope == "running":
        return summary.status == "running"
    return True


def _team_match_sort(time_scope: TimeScope) -> str:
    return "scheduled_at" if time_scope == "upcoming" else "-scheduled_at"


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
