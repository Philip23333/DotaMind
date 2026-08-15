"""Unique, explainable matching of one PandaScore game to an OpenDota match."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any

from app.integrations.match_resolution.models import (
    CrossSourceMapping,
    CrossSourceResolution,
    ResolvedValveMatch,
    TeamLeagueResolution,
)
from app.integrations.opendota.leagues import (
    OpenDotaLeague,
    OpenDotaLeagueMatch,
    OpenDotaLeagues,
)
from app.integrations.opendota.team_resolution import resolve_team
from app.integrations.opendota.teams import OpenDotaTeams


class ValveMatchResolver:
    def __init__(
        self,
        leagues: OpenDotaLeagues,
        teams: OpenDotaTeams,
        *,
        start_time_tolerance_seconds: int = 1800,
        duration_tolerance_seconds: int = 5,
    ) -> None:
        self.leagues = leagues
        self.teams = teams
        self.start_time_tolerance_seconds = max(0, start_time_tolerance_seconds)
        self.duration_tolerance_seconds = max(0, duration_tolerance_seconds)

    async def resolve(
        self,
        competition: dict[str, Any],
        game_context: dict[str, Any],
    ) -> CrossSourceResolution:
        series_name = _first_text(
            competition.get("series_name"),
            competition.get("name"),
        )
        year = _as_int(competition.get("year")) or _year_from_text(
            competition.get("full_name")
        )
        if not series_name or year is None:
            return CrossSourceResolution(
                status="insufficient_signals",
                missing_signals=["competition_name", "competition_year"],
            )

        leagues = await self.leagues.get_all()
        league_candidates = _find_league_candidates(leagues, series_name, year)
        if not league_candidates:
            return CrossSourceResolution(status="league_not_found")
        if len(league_candidates) > 1:
            return CrossSourceResolution(
                status="ambiguous_league",
                candidates=[league.model_dump(mode="json") for league in league_candidates],
            )
        league = league_candidates[0]

        panda_teams = game_context.get("teams")
        if not isinstance(panda_teams, list) or len(panda_teams) != 2:
            return CrossSourceResolution(
                status="insufficient_signals",
                league=league.model_dump(mode="json"),
                missing_signals=["teams"],
            )
        team_rows = await self.teams.get_all()
        resolved_team_rows: list[dict[str, Any]] = []
        used_league_participation = False
        for panda_team in panda_teams:
            if not isinstance(panda_team, dict):
                return CrossSourceResolution(
                    status="team_not_found",
                    league=league.model_dump(mode="json"),
                )
            query = _first_text(panda_team.get("name"), panda_team.get("acronym"))
            resolution = resolve_team(query or "", team_rows)
            if resolution.status == "not_found":
                return CrossSourceResolution(
                    status="team_not_found",
                    league=league.model_dump(mode="json"),
                    teams=[
                        {
                            "query": query,
                            "pandascore_team_id": panda_team.get("pandascore_team_id"),
                        }
                    ],
                )
            if resolution.status == "ambiguous":
                league_resolution = await self._resolve_ambiguous_team_by_league(
                    panda_team=panda_team,
                    candidates=resolution.candidates,
                    league=league,
                )
                if league_resolution.status == "ambiguous":
                    return CrossSourceResolution(
                        status="ambiguous_team",
                        league=league.model_dump(mode="json"),
                        teams=[
                            {
                                "query": query,
                                "pandascore_team_id": panda_team.get("pandascore_team_id"),
                                "reason": league_resolution.reason,
                                "target_league_id": league.opendota_league_id,
                                "candidates": resolution.candidates,
                                "diagnostics": league_resolution.diagnostics,
                            }
                        ],
                    )
                selected_team = league_resolution.team
                if not selected_team or not isinstance(selected_team.get("team_id"), int):
                    raise ValueError("league participation resolved without a team id")
                resolved_team_rows.append(
                    {
                        "pandascore_team_id": panda_team.get("pandascore_team_id"),
                        "opendota_team_id": selected_team["team_id"],
                        "name": selected_team.get("name"),
                        "tag": selected_team.get("tag"),
                        "resolution_method": "league_participation",
                        "target_league_id": league.opendota_league_id,
                        "league_match_count": next(
                            item["league_match_count"]
                            for item in league_resolution.diagnostics
                            if item.get("team_id") == selected_team["team_id"]
                        ),
                        "sample_match_ids": next(
                            item["sample_match_ids"]
                            for item in league_resolution.diagnostics
                            if item.get("team_id") == selected_team["team_id"]
                        ),
                    }
                )
                used_league_participation = True
                continue
            if not resolution.team or not isinstance(resolution.team.get("team_id"), int):
                return CrossSourceResolution(
                    status="team_not_found",
                    league=league.model_dump(mode="json"),
                )
            resolved_team_rows.append(
                {
                    "pandascore_team_id": panda_team.get("pandascore_team_id"),
                    "opendota_team_id": resolution.team["team_id"],
                    "name": resolution.team.get("name"),
                    "tag": resolution.team.get("tag"),
                    "resolution_method": "global_team_identity",
                }
            )

        target_start = _epoch_from_value(game_context.get("game_begin_at"))
        target_duration = _as_int(game_context.get("length_seconds"))
        target_position = _as_int(game_context.get("game_position"))
        missing_signals = []
        if target_start is None:
            missing_signals.append("game_begin_at")
        if target_duration is None:
            missing_signals.append("length_seconds")
        if target_position is None:
            missing_signals.append("game_position")
        if missing_signals:
            return CrossSourceResolution(
                status="insufficient_signals",
                league=league.model_dump(mode="json"),
                teams=resolved_team_rows,
                missing_signals=missing_signals,
            )

        league_matches = await self.leagues.get_matches(league.opendota_league_id)
        target_team_ids = {
            int(row["opendota_team_id"])
            for row in resolved_team_rows
        }
        candidates = [
            match
            for match in league_matches
            if self._matches_signals(
                match,
                target_team_ids=target_team_ids,
                target_start=target_start,
                target_duration=target_duration,
                target_position=target_position,
                target_winner_team_id=_winner_opendota_team_id(
                    game_context,
                    resolved_team_rows,
                ),
                all_matches=league_matches,
            )
        ]
        if not candidates:
            return CrossSourceResolution(
                status="not_found",
                league=league.model_dump(mode="json"),
                teams=resolved_team_rows,
            )
        if len(candidates) > 1:
            return CrossSourceResolution(
                status="ambiguous_match",
                league=league.model_dump(mode="json"),
                teams=resolved_team_rows,
                candidates=[candidate.model_dump(mode="json") for candidate in candidates],
            )

        candidate = candidates[0]
        delta_start = abs(int(candidate.start_time or 0) - target_start)
        delta_duration = abs(int(candidate.duration or 0) - target_duration)
        matched_on = ["league"]
        if used_league_participation:
            matched_on.append("team_league_participation")
        matched_on.extend(["team_ids", "start_time", "duration", "game_position"])
        winner_team_id = _winner_opendota_team_id(game_context, resolved_team_rows)
        if winner_team_id is not None:
            matched_on.append("winner")
        mapping = CrossSourceMapping(
            pandascore_match_id=_required_int(game_context.get("pandascore_match_id")),
            pandascore_game_id=_required_int(game_context.get("pandascore_game_id")),
            opendota_league_id=league.opendota_league_id,
            opendota_series_id=candidate.opendota_series_id,
            candidate_count=1,
            matched_on=matched_on,
            start_time_delta_seconds=delta_start,
            duration_delta_seconds=delta_duration,
        )
        return CrossSourceResolution(
            status="resolved",
            league=league.model_dump(mode="json"),
            teams=resolved_team_rows,
            match=ResolvedValveMatch(
                valve_match_id=candidate.valve_match_id,
                opendota_league_id=league.opendota_league_id,
                opendota_series_id=candidate.opendota_series_id,
            ),
            mapping=mapping,
        )

    async def _resolve_ambiguous_team_by_league(
        self,
        *,
        panda_team: dict[str, Any],
        candidates: list[dict[str, Any]],
        league: OpenDotaLeague,
    ) -> TeamLeagueResolution:
        diagnostics: list[dict[str, Any]] = []
        pandascore_team_id = panda_team.get("pandascore_team_id")
        for candidate in candidates:
            team_id = _as_int(candidate.get("team_id"))
            if team_id is None or team_id <= 0:
                diagnostics.append(
                    {
                        "team_id": candidate.get("team_id"),
                        "pandascore_team_id": pandascore_team_id,
                        "name": candidate.get("name"),
                        "tag": candidate.get("tag"),
                        "target_league_id": league.opendota_league_id,
                        "league_match_count": 0,
                        "sample_match_ids": [],
                    }
                )
                continue
            matches = await self.teams.get_matches(team_id)
            if not isinstance(matches, list):
                raise ValueError("OpenDota team matches response must be a list")
            league_matches = [
                match
                for match in matches
                if isinstance(match, dict)
                and _as_int(match.get("leagueid")) == league.opendota_league_id
            ]
            sample_match_ids = [
                match_id
                for match in league_matches
                if (match_id := _as_int(match.get("match_id"))) is not None and match_id > 0
            ][:5]
            diagnostics.append(
                {
                    "team_id": team_id,
                    "pandascore_team_id": pandascore_team_id,
                    "name": candidate.get("name"),
                    "tag": candidate.get("tag"),
                    "target_league_id": league.opendota_league_id,
                    "league_match_count": len(league_matches),
                    "sample_match_ids": sample_match_ids,
                }
            )

        matching = [
            item
            for item in diagnostics
            if item["league_match_count"] > 0
        ]
        if len(matching) != 1:
            return TeamLeagueResolution(
                status="ambiguous",
                reason=(
                    "no_candidate_in_target_league"
                    if not matching
                    else "multiple_candidates_in_target_league"
                ),
                diagnostics=diagnostics,
            )
        selected_id = matching[0]["team_id"]
        selected = next(
            candidate
            for candidate in candidates
            if _as_int(candidate.get("team_id")) == selected_id
        )
        return TeamLeagueResolution(
            status="resolved",
            team=selected,
            diagnostics=diagnostics,
        )

    def _matches_signals(
        self,
        match: OpenDotaLeagueMatch,
        *,
        target_team_ids: set[int],
        target_start: int,
        target_duration: int,
        target_position: int,
        target_winner_team_id: int | None,
        all_matches: list[OpenDotaLeagueMatch],
    ) -> bool:
        match_team_ids = {
            value
            for value in (match.radiant_team_id, match.dire_team_id)
            if value is not None
        }
        if match_team_ids != target_team_ids:
            return False
        if (
            match.start_time is None
            or abs(match.start_time - target_start) > self.start_time_tolerance_seconds
        ):
            return False
        if (
            match.duration is None
            or abs(match.duration - target_duration) > self.duration_tolerance_seconds
        ):
            return False
        if _series_position(match, all_matches) != target_position:
            return False
        if target_winner_team_id is not None and match.radiant_win is not None:
            expected_winner = (
                "radiant"
                if match.radiant_team_id == target_winner_team_id
                else "dire"
                if match.dire_team_id == target_winner_team_id
                else None
            )
            actual_winner = "radiant" if match.radiant_win else "dire"
            if expected_winner is None or actual_winner != expected_winner:
                return False
        return True


def _find_league_candidates(
    leagues: list[OpenDotaLeague], series_name: str, year: int
) -> list[OpenDotaLeague]:
    query = _normalize_text(f"{series_name} {year}")
    return [league for league in leagues if _normalize_text(league.name) == query]


def _series_position(
    match: OpenDotaLeagueMatch, all_matches: list[OpenDotaLeagueMatch]
) -> int | None:
    if match.opendota_series_id is None or match.start_time is None:
        return None
    series_matches = [
        candidate
        for candidate in all_matches
        if candidate.opendota_series_id == match.opendota_series_id
        and candidate.start_time is not None
    ]
    series_matches.sort(key=lambda candidate: (candidate.start_time, candidate.valve_match_id))
    for index, candidate in enumerate(series_matches, start=1):
        if candidate.valve_match_id == match.valve_match_id:
            return index
    return None


def _winner_opendota_team_id(
    game_context: dict[str, Any], team_rows: list[dict[str, Any]]
) -> int | None:
    winner_id = _as_int(game_context.get("winner_pandascore_team_id"))
    if winner_id is None:
        return None
    winner_team = next(
        (row for row in team_rows if row.get("pandascore_team_id") == winner_id),
        None,
    )
    if winner_team is None:
        return None
    return _as_int(winner_team.get("opendota_team_id"))


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^\w]+", "", normalized, flags=re.UNICODE)


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _year_from_text(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"\b(20\d{2})\b", value)
    return int(match.group(1)) if match else None


def _epoch_from_value(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return int(parsed.timestamp())
        except ValueError:
            return None
    return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _required_int(value: Any) -> int:
    resolved = _as_int(value)
    if resolved is None or resolved <= 0:
        raise ValueError("cross-source mapping requires a positive PandaScore id")
    return resolved
