"""Offline candidate filtering for one PandaScore Game and OpenDota League."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from pydantic import JsonValue

CandidateCategory = Literal[
    "candidates_found",
    "no_candidates",
    "insufficient_signals",
    "target_game_not_found",
    "ambiguous_target_game",
    "target_not_ready",
]
JsonObject = dict[str, JsonValue]


@dataclass(frozen=True)
class GameCandidate:
    """An unchanged OpenDota source row and its signed signal differences."""

    record: JsonObject
    start_delta_seconds: float
    duration_delta_seconds: int


@dataclass(frozen=True)
class GameCandidateResult:
    """Candidate-filter outcome; candidates are evidence, not identity claims."""

    category: CandidateCategory
    searched_league_id: int
    target_game: JsonObject | None
    candidates: tuple[GameCandidate, ...]
    unusable_record_count: int
    reason: str | None


def find_game_candidates(
    match_context: Mapping[str, JsonValue],
    game_position: int,
    league_id: int,
    league_matches: Sequence[Mapping[str, JsonValue]],
    *,
    start_time_tolerance_seconds: int,
    duration_tolerance_seconds: int,
) -> GameCandidateResult:
    """Filter one League's source rows by the selected Game's time and length.

    The function is synchronous and offline. It preserves all input mappings and
    returns every row within both explicitly supplied tolerances, in source
    order. A candidate is not a confirmed cross-source identity.
    """

    _validate_parameters(
        game_position,
        league_id,
        start_time_tolerance_seconds,
        duration_tolerance_seconds,
    )

    games_value = match_context.get("games", _MISSING)
    if games_value is _MISSING:
        return _result(
            "target_game_not_found", league_id, "games_missing"
        )
    if games_value is None:
        return _result("target_game_not_found", league_id, "games_null")
    if not isinstance(games_value, list):
        return _result("target_game_not_found", league_id, "games_invalid")
    if not games_value:
        return _result("target_game_not_found", league_id, "games_empty")

    matching_games = [
        game
        for game in games_value
        if isinstance(game, dict)
        and type(game.get("position")) is int
        and game["position"] == game_position
    ]
    if not matching_games:
        return _result("target_game_not_found", league_id, "position_not_found")
    if len(matching_games) > 1:
        return _result(
            "ambiguous_target_game", league_id, "duplicate_game_position"
        )

    target_game = matching_games[0]
    if target_game.get("forfeit") is True:
        return _result(
            "target_not_ready", league_id, "target_game_forfeit", target_game
        )
    if target_game.get("status") == "not_started":
        return _result(
            "target_not_ready", league_id, "target_game_not_started", target_game
        )

    target_start, target_start_reason = _parse_target_start(target_game)
    if target_start is None:
        return _result(
            "insufficient_signals", league_id, target_start_reason, target_game
        )

    target_length, target_length_reason = _parse_target_length(target_game)
    if target_length is None:
        return _result(
            "insufficient_signals", league_id, target_length_reason, target_game
        )

    candidates: list[GameCandidate] = []
    unusable_record_count = 0
    for record in league_matches:
        if not isinstance(record, Mapping):
            unusable_record_count += 1
            continue

        start_time = record.get("start_time")
        duration = record.get("duration")
        if type(start_time) is not int or type(duration) is not int or duration < 0:
            unusable_record_count += 1
            continue

        try:
            source_start = datetime.fromtimestamp(start_time, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            unusable_record_count += 1
            continue

        start_delta = (source_start - target_start).total_seconds()
        duration_delta = duration - target_length
        if (
            abs(start_delta) <= start_time_tolerance_seconds
            and abs(duration_delta) <= duration_tolerance_seconds
        ):
            # OpenDotaDiscoveryAdapter supplies dictionaries. Keep the exact
            # source object so every unknown field and value remains available.
            if isinstance(record, dict):
                source_record = record
            else:
                source_record = dict(record)
            candidates.append(
                GameCandidate(
                    record=source_record,
                    start_delta_seconds=start_delta,
                    duration_delta_seconds=duration_delta,
                )
            )

    if candidates:
        return GameCandidateResult(
            category="candidates_found",
            searched_league_id=league_id,
            target_game=target_game,
            candidates=tuple(candidates),
            unusable_record_count=unusable_record_count,
            reason=None,
        )

    return GameCandidateResult(
        category="no_candidates",
        searched_league_id=league_id,
        target_game=target_game,
        candidates=(),
        unusable_record_count=unusable_record_count,
        reason="no_candidate_within_tolerances",
    )


_MISSING = object()


def _validate_parameters(
    game_position: int,
    league_id: int,
    start_time_tolerance_seconds: int,
    duration_tolerance_seconds: int,
) -> None:
    if type(game_position) is not int or game_position <= 0:
        raise ValueError("game_position must be a positive integer")
    if type(league_id) is not int or league_id <= 0:
        raise ValueError("league_id must be a positive integer")
    if (
        type(start_time_tolerance_seconds) is not int
        or start_time_tolerance_seconds < 0
    ):
        raise ValueError("start_time_tolerance_seconds must be a non-negative integer")
    if (
        type(duration_tolerance_seconds) is not int
        or duration_tolerance_seconds < 0
    ):
        raise ValueError("duration_tolerance_seconds must be a non-negative integer")


def _parse_target_start(
    target_game: JsonObject,
) -> tuple[datetime | None, str]:
    value = target_game.get("begin_at", _MISSING)
    if value is _MISSING:
        return None, "begin_at_missing"
    if value is None or value == "":
        return None, "begin_at_empty"
    if not isinstance(value, str):
        return None, "begin_at_invalid"

    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError:
        return None, "begin_at_invalid"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, "begin_at_timezone_missing"
    return parsed.astimezone(timezone.utc), ""


def _parse_target_length(target_game: JsonObject) -> tuple[int | None, str]:
    value = target_game.get("length", _MISSING)
    if value is _MISSING:
        return None, "length_missing"
    if value is None or value == "":
        return None, "length_empty"
    if type(value) is not int or value < 0:
        return None, "length_invalid"
    return value, ""


def _result(
    category: CandidateCategory,
    league_id: int,
    reason: str,
    target_game: JsonObject | None = None,
) -> GameCandidateResult:
    return GameCandidateResult(
        category=category,
        searched_league_id=league_id,
        target_game=target_game,
        candidates=(),
        unusable_record_count=0,
        reason=reason,
    )


__all__ = [
    "GameCandidate",
    "GameCandidateResult",
    "find_game_candidates",
]
