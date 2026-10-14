"""Offline resolution of one PandaScore Game against League candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from pydantic import JsonValue

from .candidates import GameCandidate, GameCandidateResult, find_game_candidates
from .evidence import GameIdentityEvidence, compare_game_identity_evidence

CandidateAssessmentStatus = Literal["accepted", "excluded", "unresolved"]
ResolutionCategory = Literal[
    "resolved",
    "ambiguous",
    "evidence_insufficient",
    "mapping_conflict",
    "no_acceptable_candidate",
    "no_candidates",
    "insufficient_signals",
    "target_game_not_found",
    "ambiguous_target_game",
    "target_not_ready",
]


@dataclass(frozen=True)
class CandidateAssessment:
    """Evidence and timing differences for one distinct OpenDota game ID."""

    candidate_valve_game_id: int
    list_start_deltas_seconds: tuple[float, ...]
    list_duration_deltas_seconds: tuple[int, ...]
    detail_start_delta_seconds: float | None
    detail_duration_delta_seconds: int | None
    status: CandidateAssessmentStatus
    identity_evidence: GameIdentityEvidence | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class GameResolutionResult:
    """Resolution outcome without copying complete provider detail records."""

    category: ResolutionCategory
    pandascore_match_id: int | None
    pandascore_game_id: int | None
    game_position: int
    searched_league_id: int
    valve_game_id: int | None
    method: Literal["inferred_cross_source"] | None
    candidate_assessments: tuple[CandidateAssessment, ...]
    unusable_record_count: int
    reason: str | None


@dataclass(frozen=True)
class _CandidateGroup:
    candidate_id: int
    candidates: tuple[GameCandidate, ...]


def resolve_game(
    match_context: Mapping[str, JsonValue],
    game_position: int,
    league_id: int,
    league_matches: Sequence[Mapping[str, JsonValue]],
    candidate_details: Mapping[int, Mapping[str, JsonValue]],
    *,
    start_time_tolerance_seconds: int,
    duration_tolerance_seconds: int,
    confirmed_mappings: Mapping[int, int],
) -> GameResolutionResult:
    """Resolve one selected game using only caller-supplied source records.

    The initial time/duration filter is intentionally scoped to one supplied
    League result. A candidate is accepted only when its detail remains in the
    same window and participant plus winner evidence agree. No source is read,
    no input is mutated, and no candidate is selected based on list order or a
    similarity score.
    """

    initial = find_game_candidates(
        match_context,
        game_position,
        league_id,
        league_matches,
        start_time_tolerance_seconds=start_time_tolerance_seconds,
        duration_tolerance_seconds=duration_tolerance_seconds,
    )
    p_match_id = _positive_int(match_context.get("id"))
    target_game = initial.target_game
    p_game_id = _positive_int(target_game.get("id")) if target_game is not None else None

    if initial.category != "candidates_found":
        return GameResolutionResult(
            category=initial.category,
            pandascore_match_id=p_match_id,
            pandascore_game_id=p_game_id,
            game_position=game_position,
            searched_league_id=initial.searched_league_id,
            valve_game_id=None,
            method=None,
            candidate_assessments=(),
            unusable_record_count=initial.unusable_record_count,
            reason=initial.reason,
        )

    detail_map = _validate_candidate_details(candidate_details)
    groups = _group_candidates(initial.candidates)
    assessments = tuple(
        _assess_candidate(
            group,
            detail_map,
            match_context,
            target_game,
            start_time_tolerance_seconds,
            duration_tolerance_seconds,
        )
        for group in groups
    )

    accepted = [item for item in assessments if item.status == "accepted"]
    unresolved = [item for item in assessments if item.status == "unresolved"]

    if len(accepted) > 1:
        return _result(
            initial,
            p_match_id,
            p_game_id,
            game_position,
            "ambiguous",
            assessments,
            "multiple_candidates_accepted",
        )

    if unresolved:
        return _result(
            initial,
            p_match_id,
            p_game_id,
            game_position,
            "evidence_insufficient",
            assessments,
            "unresolved_competing_candidate"
            if accepted
            else "candidate_evidence_incomplete",
        )

    if not accepted:
        return _result(
            initial,
            p_match_id,
            p_game_id,
            game_position,
            "no_acceptable_candidate",
            assessments,
            "all_candidates_excluded",
        )

    if p_match_id is None or p_game_id is None:
        return _result(
            initial,
            p_match_id,
            p_game_id,
            game_position,
            "evidence_insufficient",
            assessments,
            "pandascore_identity_missing",
        )

    mapping_conflict = _find_mapping_conflict(
        confirmed_mappings,
        pandascore_game_id=p_game_id,
        valve_game_id=accepted[0].candidate_valve_game_id,
    )
    if mapping_conflict is not None:
        return _result(
            initial,
            p_match_id,
            p_game_id,
            game_position,
            "mapping_conflict",
            assessments,
            mapping_conflict,
        )

    return GameResolutionResult(
        category="resolved",
        pandascore_match_id=p_match_id,
        pandascore_game_id=p_game_id,
        game_position=game_position,
        searched_league_id=initial.searched_league_id,
        valve_game_id=accepted[0].candidate_valve_game_id,
        method="inferred_cross_source",
        candidate_assessments=assessments,
        unusable_record_count=initial.unusable_record_count,
        reason=None,
    )


def _assess_candidate(
    group: _CandidateGroup,
    candidate_details: Mapping[int, Mapping[str, JsonValue]],
    match_context: Mapping[str, JsonValue],
    target_game: dict[str, JsonValue] | None,
    start_tolerance: int,
    duration_tolerance: int,
) -> CandidateAssessment:
    first = group.candidates[0]
    list_start_deltas = tuple(item.start_delta_seconds for item in group.candidates)
    list_duration_deltas = tuple(
        item.duration_delta_seconds for item in group.candidates
    )
    if group.candidate_id not in candidate_details:
        return CandidateAssessment(
            candidate_valve_game_id=group.candidate_id,
            list_start_deltas_seconds=list_start_deltas,
            list_duration_deltas_seconds=list_duration_deltas,
            detail_start_delta_seconds=None,
            detail_duration_delta_seconds=None,
            status="unresolved",
            identity_evidence=None,
            reasons=("candidate_detail_missing",),
        )

    detail = candidate_details[group.candidate_id]
    detail_id = detail.get("match_id")
    if _positive_int(detail_id) != group.candidate_id:
        raise ValueError("candidate detail match_id must match its positive map key")

    target_start, target_length = _target_signals(target_game)
    detail_start = detail.get("start_time")
    detail_duration = detail.get("duration")
    detail_start_delta: float | None = None
    detail_duration_delta: int | None = None
    timing_reasons: list[str] = []

    if type(detail_start) is not int:
        timing_reasons.append("detail_start_time_unusable")
    else:
        try:
            source_start = datetime.fromtimestamp(detail_start, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            timing_reasons.append("detail_start_time_unusable")
        else:
            detail_start_delta = (source_start - target_start).total_seconds()
            if abs(detail_start_delta) > start_tolerance:
                timing_reasons.append("detail_start_outside_tolerance")

    if type(detail_duration) is not int or detail_duration < 0:
        timing_reasons.append("detail_duration_unusable")
    else:
        detail_duration_delta = detail_duration - target_length
        if abs(detail_duration_delta) > duration_tolerance:
            timing_reasons.append("detail_duration_outside_tolerance")

    if any(reason.endswith("unusable") for reason in timing_reasons):
        return CandidateAssessment(
            candidate_valve_game_id=group.candidate_id,
            list_start_deltas_seconds=list_start_deltas,
            list_duration_deltas_seconds=list_duration_deltas,
            detail_start_delta_seconds=detail_start_delta,
            detail_duration_delta_seconds=detail_duration_delta,
            status="unresolved",
            identity_evidence=None,
            reasons=tuple(timing_reasons),
        )
    if timing_reasons:
        return CandidateAssessment(
            candidate_valve_game_id=group.candidate_id,
            list_start_deltas_seconds=list_start_deltas,
            list_duration_deltas_seconds=list_duration_deltas,
            detail_start_delta_seconds=detail_start_delta,
            detail_duration_delta_seconds=detail_duration_delta,
            status="excluded",
            identity_evidence=None,
            reasons=tuple(timing_reasons),
        )

    evidence = compare_game_identity_evidence(
        match_context,
        target_game,
        first.record,
        detail,
    )
    if (
        evidence.participants_status == "supported"
        and evidence.winner_status == "conflict"
    ):
        status: CandidateAssessmentStatus = "excluded"
        reasons = ("game_winner_conflict",)
    elif (
        evidence.participants_status == "supported"
        and evidence.winner_status == "consistent"
        and not _has_source_conflict(evidence)
    ):
        status = "accepted"
        reasons = ()
    else:
        status = "unresolved"
        reasons = evidence.reasons or ("identity_evidence_incomplete",)

    return CandidateAssessment(
        candidate_valve_game_id=group.candidate_id,
        list_start_deltas_seconds=list_start_deltas,
        list_duration_deltas_seconds=list_duration_deltas,
        detail_start_delta_seconds=detail_start_delta,
        detail_duration_delta_seconds=detail_duration_delta,
        status=status,
        identity_evidence=evidence,
        reasons=reasons,
    )


def _target_signals(target_game: dict[str, JsonValue] | None) -> tuple[datetime, int]:
    if target_game is None:
        raise ValueError("candidate result is missing its target game")
    raw_start = target_game.get("begin_at")
    if not isinstance(raw_start, str) or not raw_start:
        raise ValueError("candidate target begin_at changed after filtering")
    try:
        target_start = datetime.fromisoformat(
            raw_start[:-1] + "+00:00" if raw_start.endswith("Z") else raw_start
        )
    except ValueError as error:
        raise ValueError("candidate target begin_at changed after filtering") from error
    if target_start.tzinfo is None or target_start.utcoffset() is None:
        raise ValueError("candidate target begin_at changed after filtering")
    raw_length = target_game.get("length")
    if type(raw_length) is not int or raw_length < 0:
        raise ValueError("candidate target length changed after filtering")
    return target_start.astimezone(timezone.utc), raw_length


def _group_candidates(candidates: tuple[GameCandidate, ...]) -> tuple[_CandidateGroup, ...]:
    grouped: dict[int, list[GameCandidate]] = {}
    for candidate in candidates:
        candidate_id = candidate.record.get("match_id")
        if _positive_int(candidate_id) is None:
            raise ValueError("candidate list match_id must be a positive integer")
        grouped.setdefault(candidate_id, []).append(candidate)
    return tuple(
        _CandidateGroup(candidate_id, tuple(items))
        for candidate_id, items in grouped.items()
    )


def _validate_candidate_details(
    candidate_details: Mapping[int, Mapping[str, JsonValue]],
) -> Mapping[int, Mapping[str, JsonValue]]:
    if not isinstance(candidate_details, Mapping):
        raise ValueError("candidate_details must be a mapping")
    for key, detail in candidate_details.items():
        if _positive_int(key) is None:
            raise ValueError("candidate detail keys must be positive integers")
        if not isinstance(detail, Mapping):
            raise ValueError("candidate detail values must be objects")
        if _positive_int(detail.get("match_id")) != key:
            raise ValueError("candidate detail match_id must match its positive map key")
    return candidate_details


def _find_mapping_conflict(
    confirmed_mappings: Mapping[int, int],
    *,
    pandascore_game_id: int,
    valve_game_id: int,
) -> str | None:
    if not isinstance(confirmed_mappings, Mapping):
        raise ValueError("confirmed_mappings must be a mapping")
    for game_id, mapped_valve_id in confirmed_mappings.items():
        if _positive_int(game_id) is None or _positive_int(mapped_valve_id) is None:
            raise ValueError("confirmed mappings must use positive integer IDs")
        if mapped_valve_id == valve_game_id and game_id != pandascore_game_id:
            return "valve_game_already_assigned"
    existing = confirmed_mappings.get(pandascore_game_id)
    if existing is not None and existing != valve_game_id:
        return "pandascore_game_already_mapped"
    return None


def _has_source_conflict(evidence: GameIdentityEvidence) -> bool:
    return any("source_conflict" in reason for reason in evidence.reasons)


def _positive_int(value: object) -> int | None:
    return value if type(value) is int and value > 0 else None


def _result(
    initial: GameCandidateResult,
    pandascore_match_id: int | None,
    pandascore_game_id: int | None,
    game_position: int,
    category: ResolutionCategory,
    assessments: tuple[CandidateAssessment, ...],
    reason: str,
) -> GameResolutionResult:
    return GameResolutionResult(
        category=category,
        pandascore_match_id=pandascore_match_id,
        pandascore_game_id=pandascore_game_id,
        game_position=game_position,
        searched_league_id=initial.searched_league_id,
        valve_game_id=None,
        method=None,
        candidate_assessments=assessments,
        unusable_record_count=initial.unusable_record_count,
        reason=reason,
    )


__all__ = [
    "CandidateAssessment",
    "CandidateAssessmentStatus",
    "GameResolutionResult",
    "ResolutionCategory",
    "resolve_game",
]
