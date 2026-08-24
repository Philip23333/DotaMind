"""Pure deterministic PandaScore-to-OpenDota match resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.vnext.domain.common.models import normalize_text
from app.vnext.domain.matches.models import ResolutionEvidence, ResolutionStatus


@dataclass(frozen=True, slots=True)
class LeagueSignal:
    provider_id: int
    name: str
    year: int | None = None


@dataclass(frozen=True, slots=True)
class TeamSignal:
    provider_id: int
    name: str
    tag: str | None = None
    fixture_id: int | None = None


@dataclass(frozen=True, slots=True)
class MatchSignal:
    provider_id: int
    competition_name: str
    competition_year: int | None
    teams: tuple[TeamSignal, ...]
    start_time: int | None
    duration_seconds: int | None
    winner_team_id: int | None = None


@dataclass(frozen=True, slots=True)
class LeagueMatchSignal:
    provider_id: int
    league_id: int
    start_time: int | None
    duration_seconds: int | None
    radiant_team_id: int | None
    dire_team_id: int | None
    radiant_win: bool | None = None


@dataclass(frozen=True, slots=True)
class ResolutionDecision:
    status: ResolutionStatus
    candidate_count: int = 0
    signals: tuple[str, ...] = ()
    candidate_evidence: tuple[ResolutionEvidence, ...] = ()
    resolved_provider_match_id: int | None = None
    warnings: tuple[str, ...] = ()


class MatchResolutionService:
    """Apply only the documented exact identity and tolerance rules.

    Provider IDs are accepted as internal data-layer signals and never appear
    in the returned agent-visible ``ResolutionSummary``.
    """

    def __init__(
        self,
        *,
        start_time_tolerance_seconds: int = 1800,
        duration_tolerance_seconds: int = 5,
    ) -> None:
        if start_time_tolerance_seconds < 0 or duration_tolerance_seconds < 0:
            raise ValueError("resolution tolerances must not be negative")
        self.start_time_tolerance_seconds = start_time_tolerance_seconds
        self.duration_tolerance_seconds = duration_tolerance_seconds

    def matching_leagues(
        self,
        competition_name: str,
        competition_year: int | None,
        leagues: list[LeagueSignal],
    ) -> list[LeagueSignal]:
        if competition_year is None:
            return []
        return [
            league
            for league in leagues
            if _league_matches(competition_name, competition_year, league)
        ]

    def resolve(
        self,
        fixture: MatchSignal,
        leagues: list[LeagueSignal],
        team_candidates: dict[str, list[TeamSignal]],
        league_matches: dict[int, list[LeagueMatchSignal]],
    ) -> ResolutionDecision:
        if len(fixture.teams) != 2 or not fixture.competition_name.strip():
            return ResolutionDecision(
                status="insufficient_signals",
                warnings=("two team signals and a competition name are required",),
            )

        if fixture.competition_year is None:
            return ResolutionDecision(
                status="insufficient_signals",
                warnings=("competition year is required for league resolution",),
            )

        matching_leagues = self.matching_leagues(
            fixture.competition_name,
            fixture.competition_year,
            leagues,
        )
        if not matching_leagues:
            return ResolutionDecision(
                status="league_not_found",
                warnings=("no unique OpenDota league matched the competition name and year",),
            )
        if len(matching_leagues) > 1:
            return ResolutionDecision(
                status="ambiguous_league",
                candidate_count=len(matching_leagues),
                warnings=("multiple OpenDota leagues matched the competition name and year",),
            )

        league = matching_leagues[0]
        participants = {
            team_id
            for match in league_matches.get(league.provider_id, [])
            for team_id in (match.radiant_team_id, match.dire_team_id)
            if team_id is not None
        }
        selected: list[TeamSignal] = []
        signals: list[str] = ["competition_name_year"]
        for fixture_team in fixture.teams:
            candidates = _deduplicate_team_candidates(
                team_candidates.get(normalize_text(fixture_team.name), [])
            )
            if not candidates:
                return ResolutionDecision(
                    status="team_not_found",
                    warnings=(f"no OpenDota team matched {fixture_team.name}",),
                )
            if len(candidates) == 1:
                selected.append(_attach_fixture_id(candidates[0], fixture_team.fixture_id))
                signals.append("team_name_exact")
                continue
            participating = [
                candidate for candidate in candidates if candidate.provider_id in participants
            ]
            if len(participating) == 1:
                selected.append(_attach_fixture_id(participating[0], fixture_team.fixture_id))
                signals.append("team_league_participation")
                continue
            if not participating:
                return ResolutionDecision(
                    status="team_not_found",
                    warnings=(
                        "none of the OpenDota team candidates for "
                        f"{fixture_team.name} participated in the target league",
                    ),
                )
            return ResolutionDecision(
                status="ambiguous_team",
                candidate_count=len(participating),
                warnings=(
                    "multiple OpenDota team candidates for "
                    f"{fixture_team.name} participated in the target league",
                ),
            )

        expected_team_ids = frozenset(team.provider_id for team in selected)
        if len(expected_team_ids) != 2:
            return ResolutionDecision(
                status="insufficient_signals",
                warnings=("the two team signals did not resolve to distinct teams",),
            )

        candidate_rows = [
            row
            for row in league_matches.get(league.provider_id, [])
            if frozenset((row.radiant_team_id, row.dire_team_id)) == expected_team_ids
        ]
        if not candidate_rows:
            return ResolutionDecision(
                status="not_found",
                signals=tuple((*signals, "unordered_team_ids")),
                warnings=("no match in the target league had the same unordered team pair",),
            )

        if fixture.start_time is None or fixture.duration_seconds is None:
            return ResolutionDecision(
                status="insufficient_signals",
                candidate_count=len(candidate_rows),
                signals=tuple((*signals, "unordered_team_ids")),
                warnings=("start time and duration are required to resolve a match",),
            )

        valid_rows: list[tuple[LeagueMatchSignal, ResolutionEvidence]] = []
        incomplete_rows = False
        rejected_by_time = False
        rejected_by_duration = False
        rejected_by_winner = False
        for row in candidate_rows:
            if row.start_time is None or row.duration_seconds is None:
                incomplete_rows = True
                continue
            start_delta = abs(fixture.start_time - row.start_time)
            duration_delta = abs(fixture.duration_seconds - row.duration_seconds)
            if start_delta > self.start_time_tolerance_seconds:
                rejected_by_time = True
                continue
            if duration_delta > self.duration_tolerance_seconds:
                rejected_by_duration = True
                continue
            winner_consistent = _winner_consistency(fixture, row, selected)
            if fixture.winner_team_id is not None and winner_consistent is None:
                incomplete_rows = True
                continue
            if winner_consistent is False:
                rejected_by_winner = True
                continue
            evidence = ResolutionEvidence(
                start_time_delta_seconds=float(start_delta),
                duration_delta_seconds=float(duration_delta),
                winner_consistent=winner_consistent,
            )
            valid_rows.append((row, evidence))

        if incomplete_rows:
            return ResolutionDecision(
                status="insufficient_signals",
                candidate_count=len(candidate_rows),
                signals=tuple((*signals, "unordered_team_ids")),
                candidate_evidence=tuple(item[1] for item in valid_rows),
                warnings=(
                    "a credible team-pair candidate lacked a required time, duration, "
                    "or winner signal",
                ),
            )
        if not valid_rows:
            warnings: list[str] = []
            if rejected_by_time:
                warnings.append("all team-pair candidates exceeded the start-time tolerance")
            if rejected_by_duration:
                warnings.append("all remaining candidates exceeded the duration tolerance")
            if rejected_by_winner:
                warnings.append("all remaining candidates failed winner consistency")
            return ResolutionDecision(
                status="not_found",
                candidate_count=len(candidate_rows),
                signals=tuple((*signals, "unordered_team_ids")),
                warnings=tuple(warnings or ("no candidate satisfied all resolution signals",)),
            )

        evidence = tuple(item[1] for item in valid_rows)
        resolution_signals = [
            *signals,
            "unordered_team_ids",
            f"start_time_delta<={self.start_time_tolerance_seconds}s",
            f"duration_delta<={self.duration_tolerance_seconds}s",
        ]
        if any(item.winner_consistent is not None for item in evidence):
            resolution_signals.append("winner_consistency")
        if len(valid_rows) > 1:
            return ResolutionDecision(
                status="ambiguous_match",
                candidate_count=len(valid_rows),
                signals=tuple(resolution_signals),
                candidate_evidence=evidence,
                warnings=("multiple credible candidates satisfied every resolution signal",),
            )
        row, _ = valid_rows[0]
        return ResolutionDecision(
            status="resolved",
            candidate_count=1,
            signals=tuple(resolution_signals),
            candidate_evidence=evidence,
            resolved_provider_match_id=row.provider_id,
            warnings=(),
        )


def _league_matches(name: str, year: int, league: LeagueSignal) -> bool:
    league_year = league.year or _extract_year(league.name)
    if league_year != year:
        return False
    return _without_year(name) == _without_year(league.name)


def _without_year(value: str) -> str:
    normalized = normalize_text(value)
    return normalize_text(re.sub(r"\b(?:19|20)\d{2}\b", " ", normalized))


def _extract_year(value: str) -> int | None:
    match = re.search(r"\b((?:19|20)\d{2})\b", value)
    return int(match.group(1)) if match else None


def _deduplicate_team_candidates(candidates: list[TeamSignal]) -> list[TeamSignal]:
    result: dict[int, TeamSignal] = {}
    for candidate in candidates:
        result.setdefault(candidate.provider_id, candidate)
    return list(result.values())


def _attach_fixture_id(candidate: TeamSignal, fixture_id: int | None) -> TeamSignal:
    return TeamSignal(
        provider_id=candidate.provider_id,
        name=candidate.name,
        tag=candidate.tag,
        fixture_id=fixture_id,
    )


def _winner_consistency(
    fixture: MatchSignal,
    row: LeagueMatchSignal,
    selected: list[TeamSignal],
) -> bool | None:
    if fixture.winner_team_id is None or row.radiant_win is None:
        return None
    selected_by_fixture_id = {
        team.fixture_id: team.provider_id for team in selected if team.fixture_id is not None
    }
    expected_open_dota_id = selected_by_fixture_id.get(fixture.winner_team_id)
    if expected_open_dota_id is None:
        return None
    actual_open_dota_id = row.radiant_team_id if row.radiant_win else row.dire_team_id
    if actual_open_dota_id is None:
        return None
    return expected_open_dota_id == actual_open_dota_id


__all__ = [
    "LeagueMatchSignal",
    "LeagueSignal",
    "MatchResolutionService",
    "MatchSignal",
    "ResolutionDecision",
    "TeamSignal",
]
