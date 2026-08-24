"""PandaScore-to-domain normalization shared by competition and match services."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from app.vnext.domain.common.models import (
    CompetitionRef,
    Freshness,
    GameRef,
    MatchRef,
    Provenance,
    Team,
    TeamRef,
    hash_ref,
    normalize_text,
)
from app.vnext.domain.matches.models import (
    CompetitionSummary,
    GameDetail,
    MatchResult,
    MatchStatus,
    MatchSummary,
    TeamScore,
)
from app.vnext.providers.pandascore.models import PandaScoreGame, PandaScoreMatch


@dataclass(frozen=True, slots=True)
class NormalizedGame:
    provider_id: int
    public: GameDetail
    start_time: int | None
    duration_seconds: int | None
    winner_provider_id: int | None


@dataclass(frozen=True, slots=True)
class NormalizedPandaMatch:
    provider_id: int
    series_id: int | None
    summary: MatchSummary
    games: tuple[NormalizedGame, ...]
    teams_by_provider_id: dict[int, Team]
    winner_provider_id: int | None
    competition_name: str
    competition_year: int | None


def normalize_panda_match(
    row: PandaScoreMatch,
    *,
    fetched_at: datetime,
    competition_ref: CompetitionRef | None = None,
    competition_name: str | None = None,
    competition_year: int | None = None,
) -> NormalizedPandaMatch:
    series_id = row.series_id or (row.series.provider_id if row.series else None)
    resolved_competition_name = competition_name or _canonical_competition_name(row)
    resolved_year = competition_year or _series_year(row)
    resolved_competition_ref = competition_ref or (
        CompetitionRef(value=hash_ref("competition", "pandascore-series", series_id))
        if series_id is not None
        else CompetitionRef(
            value=hash_ref(
                "competition",
                "pandascore-name",
                resolved_competition_name,
                resolved_year,
            )
        )
    )

    teams_by_provider_id: dict[int, Team] = {}
    teams: list[Team] = []
    for opponent in row.opponents:
        team = opponent.opponent
        if team.provider_id in teams_by_provider_id:
            continue
        public_team = Team(
            ref=TeamRef(value=hash_ref("team", "pandascore", team.provider_id)),
            name=team.name,
            acronym=team.acronym,
            logo_url=team.image_url,
        )
        teams_by_provider_id[team.provider_id] = public_team
        teams.append(public_team)

    result, winner_provider_id, result_warnings = _normalize_result(row, teams_by_provider_id)
    warnings = list(result_warnings)
    if row.scheduled_at is None and row.begin_at is None:
        warnings.append("PandaScore did not provide a scheduled or start time")
    if row.complete is False:
        warnings.append("PandaScore post-game statistics are not final")
    if row.detailed_stats is False:
        warnings.append("PandaScore coverage is fixture and result level only")

    provenance = Provenance(
        sources=["pandascore"],
        freshness=Freshness(fetched_at=fetched_at, status="fresh"),
        identity_status="native",
        warnings=warnings,
    )
    summary = MatchSummary(
        ref=MatchRef(value=hash_ref("match", "pandascore", row.provider_id)),
        name=row.name,
        competition=CompetitionSummary(
            ref=resolved_competition_ref,
            name=resolved_competition_name,
            year=resolved_year,
        ),
        teams=teams,
        scheduled_at=row.scheduled_at,
        started_at=row.begin_at,
        ended_at=row.end_at,
        status=_match_status(row.status),
        result=result,
        games_count=row.number_of_games or len(row.games) or None,
        provenance=provenance,
    )

    games = tuple(
        _normalize_game(
            game,
            row=row,
            fetched_at=fetched_at,
            teams_by_provider_id=teams_by_provider_id,
        )
        for game in row.games
    )
    return NormalizedPandaMatch(
        provider_id=row.provider_id,
        series_id=series_id,
        summary=summary,
        games=games,
        teams_by_provider_id=teams_by_provider_id,
        winner_provider_id=winner_provider_id,
        competition_name=resolved_competition_name,
        competition_year=resolved_year,
    )


def _normalize_game(
    game: PandaScoreGame,
    *,
    row: PandaScoreMatch,
    fetched_at: datetime,
    teams_by_provider_id: dict[int, Team],
) -> NormalizedGame:
    winner_provider_id = game.winner.provider_id if game.winner else None
    winner_ref = (
        teams_by_provider_id[winner_provider_id].ref
        if winner_provider_id in teams_by_provider_id
        else None
    )
    start_at = game.begin_at or game.scheduled_at or row.begin_at or row.scheduled_at
    end_at = game.end_at
    warnings: list[str] = []
    if game.complete is False:
        warnings.append("PandaScore game statistics are not final")
    if game.detailed_stats is False:
        warnings.append("PandaScore game detailed statistics are unavailable")
    public = GameDetail(
        ref=GameRef(value=hash_ref("game", "pandascore", row.provider_id, game.provider_id)),
        position=game.position,
        status=_match_status(game.status or "unknown"),
        scheduled_at=game.scheduled_at,
        started_at=game.begin_at,
        ended_at=end_at,
        duration_seconds=game.length,
        winner=winner_ref,
        detail_status="fixture_only",
        coverage=["pandascore_fixture"],
        provenance=Provenance(
            sources=["pandascore"],
            freshness=Freshness(fetched_at=fetched_at, status="fresh"),
            identity_status="native",
            warnings=warnings,
        ),
    )
    return NormalizedGame(
        provider_id=game.provider_id,
        public=public,
        start_time=_epoch_seconds(start_at),
        duration_seconds=game.length or _duration_seconds(start_at, end_at),
        winner_provider_id=winner_provider_id,
    )


def _normalize_result(
    row: PandaScoreMatch,
    teams_by_provider_id: dict[int, Team],
) -> tuple[MatchResult | None, int | None, list[str]]:
    scores: list[TeamScore] = []
    warnings: list[str] = []
    for result in row.results:
        if result.team_id is None or result.team_id not in teams_by_provider_id:
            warnings.append("PandaScore returned a result for an unknown team")
            continue
        scores.append(
            TeamScore(
                team=teams_by_provider_id[result.team_id].ref,
                score=result.score,
            )
        )
    winner_provider_id: int | None = None
    known_scores = [item for item in row.results if item.team_id in teams_by_provider_id]
    if len(known_scores) >= 2:
        ordered = sorted(
            known_scores,
            key=lambda item: item.score if item.score is not None else -1,
            reverse=True,
        )
        if ordered[0].score is not None and ordered[0].score > (ordered[1].score or -1):
            winner_provider_id = ordered[0].team_id
    if not scores:
        return None, winner_provider_id, warnings
    return (
        MatchResult(
            winner=(
                teams_by_provider_id[winner_provider_id].ref
                if winner_provider_id is not None
                else None
            ),
            scores=scores,
        ),
        winner_provider_id,
        warnings,
    )


def _match_status(value: str) -> MatchStatus:
    normalized = normalize_text(value.replace("_", " "))
    if normalized in {"not started", "scheduled", "upcoming"}:
        return "scheduled"
    if normalized in {"running", "live", "in progress"}:
        return "running"
    if normalized in {"finished", "completed"}:
        return "finished"
    if normalized in {"canceled", "cancelled"}:
        return "cancelled"
    if normalized == "postponed":
        return "postponed"
    return "unknown"


def _epoch_seconds(value: datetime | None) -> int | None:
    return int(value.timestamp()) if value is not None else None


def _duration_seconds(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds()))


def _extract_year(value: str) -> int | None:
    match = re.search(r"\b((?:19|20)\d{2})\b", value)
    return int(match.group(1)) if match else None


def _canonical_competition_name(row: PandaScoreMatch) -> str:
    series = row.series
    series_name = series.name.strip() if series and series.name else ""
    series_full_name = series.full_name.strip() if series and series.full_name else ""
    league_name = row.league.name.strip() if row.league and row.league.name else ""
    if not series_name or _is_year_only(series_name) or _is_year_only(series_full_name):
        return league_name or series_name or series_full_name or "Unknown competition"
    return series_name


def _series_year(row: PandaScoreMatch) -> int | None:
    if row.series is None:
        return None
    return (
        row.series.year
        or _extract_year(row.series.full_name or "")
        or _extract_year(row.series.name or "")
    )


def _is_year_only(value: str) -> bool:
    return bool(re.fullmatch(r"(?:19|20)\d{2}", value.strip()))


__all__ = ["NormalizedGame", "NormalizedPandaMatch", "normalize_panda_match"]
