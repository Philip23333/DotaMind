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
MultiLeagueResolutionCategory = Literal[
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
    "search_scope_incomplete",
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
class LeagueScopedCandidateAssessment:
    """One League's assessment of a Valve game candidate."""

    league_id: int
    assessment: CandidateAssessment


@dataclass(frozen=True)
class MultiLeagueCandidateAssessment:
    """Merged assessment for one Valve ID with every League evaluation retained."""

    candidate_valve_game_id: int
    league_assessments: tuple[LeagueScopedCandidateAssessment, ...]
    status: CandidateAssessmentStatus
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class LeagueSearchDiagnostic:
    """Candidate-list quality for a selected League; None means not supplied."""

    league_id: int
    unusable_record_count: int | None


@dataclass(frozen=True)
class MultiLeagueGameResolutionResult:
    """Cross-League result; selected Leagues remain search scopes, not identities."""

    category: MultiLeagueResolutionCategory
    pandascore_match_id: int | None
    pandascore_game_id: int | None
    game_position: int
    searched_league_ids: tuple[int, ...]
    missing_league_ids: tuple[int, ...]
    valve_game_id: int | None
    method: Literal["inferred_cross_source"] | None
    candidate_assessments: tuple[MultiLeagueCandidateAssessment, ...]
    league_search_diagnostics: tuple[LeagueSearchDiagnostic, ...]
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


def resolve_game_across_leagues(
    match_context: Mapping[str, JsonValue],
    game_position: int,
    league_ids: Sequence[int],
    league_matches_by_id: Mapping[int, Sequence[Mapping[str, JsonValue]]],
    candidate_details: Mapping[int, Mapping[str, JsonValue]],
    *,
    start_time_tolerance_seconds: int,
    duration_tolerance_seconds: int,
    confirmed_mappings: Mapping[int, int],
) -> MultiLeagueGameResolutionResult:
    """Resolve a selected game across every caller-selected League scope.

    Candidate assessments are merged only after each League has been evaluated.
    A missing selected list leaves the search incomplete, even if the supplied
    Leagues otherwise yield a unique accepted candidate.
    """

    if not isinstance(match_context, Mapping):
        raise ValueError("match_context must be an object")
    selected_league_ids = _validate_league_ids(league_ids)
    validated_lists = _validate_league_match_map(league_matches_by_id)
    _validate_candidate_details(candidate_details)
    if not isinstance(confirmed_mappings, Mapping):
        raise ValueError("confirmed_mappings must be a mapping")

    # Reuse the existing target selection and signal validation before examining
    # any League. An empty list is enough to validate and retain the target facts.
    probe_league_id = selected_league_ids[0] if selected_league_ids else 1
    target_probe = find_game_candidates(
        match_context,
        game_position,
        probe_league_id,
        [],
        start_time_tolerance_seconds=start_time_tolerance_seconds,
        duration_tolerance_seconds=duration_tolerance_seconds,
    )
    pandascore_match_id = _positive_int(match_context.get("id"))
    target_game = target_probe.target_game
    pandascore_game_id = (
        _positive_int(target_game.get("id")) if target_game is not None else None
    )

    if not selected_league_ids:
        return _multi_league_result(
            target_probe,
            pandascore_match_id,
            pandascore_game_id,
            game_position,
            (),
            (),
            (),
            (),
            "no_candidates",
            "no_league_candidates",
        )

    if target_probe.category not in {"candidates_found", "no_candidates"}:
        diagnostics = tuple(
            LeagueSearchDiagnostic(league_id, None)
            for league_id in selected_league_ids
        )
        return _multi_league_result(
            target_probe,
            pandascore_match_id,
            pandascore_game_id,
            game_position,
            selected_league_ids,
            tuple(
                league_id
                for league_id in selected_league_ids
                if league_id not in validated_lists
            ),
            (),
            diagnostics,
            target_probe.category,
            target_probe.reason,
        )

    missing_league_ids = tuple(
        league_id
        for league_id in selected_league_ids
        if league_id not in validated_lists
    )
    assessments_by_candidate: dict[int, list[LeagueScopedCandidateAssessment]] = {}
    diagnostics_by_league: dict[int, LeagueSearchDiagnostic] = {}

    for league_id in selected_league_ids:
        league_matches = validated_lists.get(league_id)
        if league_matches is None:
            diagnostics_by_league[league_id] = LeagueSearchDiagnostic(
                league_id, None
            )
            continue

        result = resolve_game(
            match_context,
            game_position,
            league_id,
            league_matches,
            candidate_details,
            start_time_tolerance_seconds=start_time_tolerance_seconds,
            duration_tolerance_seconds=duration_tolerance_seconds,
            confirmed_mappings={},
        )
        diagnostics_by_league[league_id] = LeagueSearchDiagnostic(
            league_id, result.unusable_record_count
        )
        for assessment in result.candidate_assessments:
            assessments_by_candidate.setdefault(
                assessment.candidate_valve_game_id, []
            ).append(
                LeagueScopedCandidateAssessment(
                    league_id=league_id,
                    assessment=assessment,
                )
            )

    merged_assessments = tuple(
        _merge_league_assessments(candidate_id, source_assessments)
        for candidate_id, source_assessments in assessments_by_candidate.items()
    )
    diagnostics = tuple(diagnostics_by_league[league_id] for league_id in selected_league_ids)

    if missing_league_ids:
        return _multi_league_result(
            target_probe,
            pandascore_match_id,
            pandascore_game_id,
            game_position,
            selected_league_ids,
            missing_league_ids,
            merged_assessments,
            diagnostics,
            "search_scope_incomplete",
            "selected_league_list_missing",
        )

    accepted = [item for item in merged_assessments if item.status == "accepted"]
    unresolved = [item for item in merged_assessments if item.status == "unresolved"]

    if len(accepted) > 1:
        return _multi_league_result(
            target_probe,
            pandascore_match_id,
            pandascore_game_id,
            game_position,
            selected_league_ids,
            (),
            merged_assessments,
            diagnostics,
            "ambiguous",
            "multiple_candidates_accepted",
        )
    if unresolved:
        return _multi_league_result(
            target_probe,
            pandascore_match_id,
            pandascore_game_id,
            game_position,
            selected_league_ids,
            (),
            merged_assessments,
            diagnostics,
            "evidence_insufficient",
            "unresolved_competing_candidate"
            if accepted
            else "candidate_evidence_incomplete",
        )
    if not accepted:
        if merged_assessments:
            category: MultiLeagueResolutionCategory = "no_acceptable_candidate"
            reason = "all_candidates_excluded"
        else:
            category = "no_candidates"
            reason = "no_candidates_in_selected_leagues"
        return _multi_league_result(
            target_probe,
            pandascore_match_id,
            pandascore_game_id,
            game_position,
            selected_league_ids,
            (),
            merged_assessments,
            diagnostics,
            category,
            reason,
        )

    if pandascore_match_id is None or pandascore_game_id is None:
        return _multi_league_result(
            target_probe,
            pandascore_match_id,
            pandascore_game_id,
            game_position,
            selected_league_ids,
            (),
            merged_assessments,
            diagnostics,
            "evidence_insufficient",
            "pandascore_identity_missing",
        )

    mapping_conflict = _find_mapping_conflict(
        confirmed_mappings,
        pandascore_game_id=pandascore_game_id,
        valve_game_id=accepted[0].candidate_valve_game_id,
    )
    if mapping_conflict is not None:
        return _multi_league_result(
            target_probe,
            pandascore_match_id,
            pandascore_game_id,
            game_position,
            selected_league_ids,
            (),
            merged_assessments,
            diagnostics,
            "mapping_conflict",
            mapping_conflict,
        )

    return _multi_league_result(
        target_probe,
        pandascore_match_id,
        pandascore_game_id,
        game_position,
        selected_league_ids,
        (),
        merged_assessments,
        diagnostics,
        "resolved",
        None,
        valve_game_id=accepted[0].candidate_valve_game_id,
        method="inferred_cross_source",
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


def _validate_league_ids(league_ids: Sequence[int]) -> tuple[int, ...]:
    if not isinstance(league_ids, Sequence) or isinstance(
        league_ids, (str, bytes, bytearray)
    ):
        raise ValueError("league_ids must be a sequence")
    result: list[int] = []
    seen: set[int] = set()
    for league_id in league_ids:
        if type(league_id) is not int or league_id <= 0:
            raise ValueError("league_ids must contain positive integers")
        if league_id not in seen:
            seen.add(league_id)
            result.append(league_id)
    return tuple(result)


def _validate_league_match_map(
    league_matches_by_id: Mapping[int, Sequence[Mapping[str, JsonValue]]],
) -> Mapping[int, Sequence[Mapping[str, JsonValue]]]:
    if not isinstance(league_matches_by_id, Mapping):
        raise ValueError("league_matches_by_id must be a mapping")
    for league_id, matches in league_matches_by_id.items():
        if type(league_id) is not int or league_id <= 0:
            raise ValueError("league match keys must be positive integers")
        if not isinstance(matches, Sequence) or isinstance(
            matches, (str, bytes, bytearray)
        ):
            raise ValueError("each League match value must be a sequence")
    return league_matches_by_id


def _merge_league_assessments(
    candidate_id: int,
    source_assessments: list[LeagueScopedCandidateAssessment],
) -> MultiLeagueCandidateAssessment:
    statuses = {item.assessment.status for item in source_assessments}
    reasons = list(
        dict.fromkeys(
            reason
            for item in source_assessments
            for reason in item.assessment.reasons
        )
    )
    has_cross_source_conflict = {"accepted", "excluded"}.issubset(statuses)
    if has_cross_source_conflict and "cross_league_assessment_conflict" not in reasons:
        reasons.append("cross_league_assessment_conflict")

    if statuses == {"accepted"}:
        status: CandidateAssessmentStatus = "accepted"
        reasons = []
    elif statuses == {"excluded"}:
        status = "excluded"
    else:
        status = "unresolved"

    return MultiLeagueCandidateAssessment(
        candidate_valve_game_id=candidate_id,
        league_assessments=tuple(source_assessments),
        status=status,
        reasons=tuple(reasons),
    )


def _multi_league_result(
    _target_probe: GameCandidateResult,
    pandascore_match_id: int | None,
    pandascore_game_id: int | None,
    game_position: int,
    searched_league_ids: tuple[int, ...],
    missing_league_ids: tuple[int, ...],
    candidate_assessments: tuple[MultiLeagueCandidateAssessment, ...],
    league_search_diagnostics: tuple[LeagueSearchDiagnostic, ...],
    category: MultiLeagueResolutionCategory,
    reason: str | None,
    *,
    valve_game_id: int | None = None,
    method: Literal["inferred_cross_source"] | None = None,
) -> MultiLeagueGameResolutionResult:
    return MultiLeagueGameResolutionResult(
        category=category,
        pandascore_match_id=pandascore_match_id,
        pandascore_game_id=pandascore_game_id,
        game_position=game_position,
        searched_league_ids=searched_league_ids,
        missing_league_ids=missing_league_ids,
        valve_game_id=valve_game_id,
        method=method,
        candidate_assessments=candidate_assessments,
        league_search_diagnostics=league_search_diagnostics,
        reason=reason,
    )


__all__ = [
    "CandidateAssessment",
    "CandidateAssessmentStatus",
    "GameResolutionResult",
    "LeagueScopedCandidateAssessment",
    "LeagueSearchDiagnostic",
    "MultiLeagueCandidateAssessment",
    "MultiLeagueGameResolutionResult",
    "MultiLeagueResolutionCategory",
    "ResolutionCategory",
    "resolve_game_across_leagues",
    "resolve_game",
]
