"""Offline participant and single-game winner evidence comparison."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue

Side = Literal["radiant", "dire"]
EvidenceStatus = Literal["supported", "unknown"]
WinnerStatus = Literal["consistent", "conflict", "unknown"]
_MISSING = object()
_COMMON_TEAM_SUFFIX = re.compile(r"(?:^|[\W_]+)(?:esports|e-sports|gaming)[\W_]*$")


@dataclass(frozen=True)
class ParticipantFact:
    """Relevant source facts for one named participant."""

    source: Literal["pandascore", "opendota"]
    side: Side | None
    team_id: JsonValue | None
    team_id_present: bool
    team_id_path: str | None
    name: JsonValue | None
    name_present: bool
    normalized_name: str | None


@dataclass(frozen=True)
class ParticipantAssociation:
    """Temporary name-based association between the two source participants."""

    pandascore_team_id: int | None
    opendota_side: Side
    opendota_team_id: int | None
    pandascore_name: str
    opendota_name: str
    name_match_method: Literal["normalized_exact", "common_suffix"] = "normalized_exact"


@dataclass(frozen=True)
class GameIdentityFacts:
    """Small source-fact projection used to explain the comparison."""

    pandascore_participants: tuple[ParticipantFact, ...]
    opendota_participants: tuple[ParticipantFact, ...]
    pandascore_opponent_count: int
    pandascore_winner: JsonValue | None
    pandascore_winner_present: bool
    pandascore_winner_id_field: JsonValue | None
    pandascore_winner_id_field_present: bool
    pandascore_winner_type_field: JsonValue | None
    pandascore_winner_type_field_present: bool
    opendota_radiant_win: JsonValue | None
    opendota_radiant_win_present: bool


@dataclass(frozen=True)
class GameIdentityEvidence:
    """Evidence for one candidate; this result never confirms identity."""

    candidate_valve_game_id: int
    participants_status: EvidenceStatus
    winner_status: WinnerStatus
    participant_associations: tuple[ParticipantAssociation, ...]
    facts: GameIdentityFacts
    reasons: tuple[str, ...]


def compare_game_identity_evidence(
    match_context: Mapping[str, JsonValue],
    target_game: Mapping[str, JsonValue],
    candidate_record: Mapping[str, JsonValue],
    candidate_detail: Mapping[str, JsonValue],
) -> GameIdentityEvidence:
    """Compare source participant names and the selected game's winner only.

    All inputs must already have been obtained by their Provider adapters. The
    candidate League row and detail must identify the same OpenDota game. This
    function does not fetch data, mutate source records, or decide whether the
    evidence is sufficient to accept a cross-source identity.
    """

    if not all(
        isinstance(value, Mapping)
        for value in (match_context, target_game, candidate_record, candidate_detail)
    ):
        raise ValueError("source records must be objects")

    list_match_id = candidate_record.get("match_id", _MISSING)
    detail_match_id = candidate_detail.get("match_id", _MISSING)
    if (
        type(list_match_id) is not int
        or list_match_id <= 0
        or type(detail_match_id) is not int
        or detail_match_id <= 0
        or list_match_id != detail_match_id
    ):
        raise ValueError("candidate detail match_id must match a positive candidate ID")

    reasons: list[str] = []
    pandascore_participants, opponent_count = _pandascore_participants(
        match_context, reasons
    )
    opendota_participants = _opendota_participants(candidate_detail, reasons)
    participants_status, associations = _compare_participants(
        pandascore_participants,
        opponent_count,
        opendota_participants,
        reasons,
    )

    winner, winner_present = _read(target_game, "winner")
    winner_id_field, winner_id_field_present = _read(target_game, "winner_id")
    winner_type_field, winner_type_field_present = _read(target_game, "winner_type")
    radiant_win, radiant_win_present = _read(candidate_detail, "radiant_win")
    facts = GameIdentityFacts(
        pandascore_participants=tuple(pandascore_participants),
        opendota_participants=tuple(opendota_participants),
        pandascore_opponent_count=opponent_count,
        pandascore_winner=winner if winner_present else None,
        pandascore_winner_present=winner_present,
        pandascore_winner_id_field=(
            winner_id_field if winner_id_field_present else None
        ),
        pandascore_winner_id_field_present=winner_id_field_present,
        pandascore_winner_type_field=(
            winner_type_field if winner_type_field_present else None
        ),
        pandascore_winner_type_field_present=winner_type_field_present,
        opendota_radiant_win=radiant_win if radiant_win_present else None,
        opendota_radiant_win_present=radiant_win_present,
    )
    winner_status = _compare_winner(
        winner,
        winner_present,
        winner_id_field,
        winner_id_field_present,
        winner_type_field,
        winner_type_field_present,
        radiant_win,
        radiant_win_present,
        participants_status,
        pandascore_participants,
        associations,
        reasons,
    )

    return GameIdentityEvidence(
        candidate_valve_game_id=detail_match_id,
        participants_status=participants_status,
        winner_status=winner_status,
        participant_associations=tuple(associations),
        facts=facts,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _pandascore_participants(
    match_context: Mapping[str, JsonValue],
    reasons: list[str],
) -> tuple[list[ParticipantFact], int]:
    raw_opponents = match_context.get("opponents", _MISSING)
    if not isinstance(raw_opponents, list):
        _add_reason(reasons, "participant_name_missing")
        return [], 0

    facts: list[ParticipantFact] = []
    if len(raw_opponents) < 2:
        _add_reason(reasons, "participant_name_missing")
    elif len(raw_opponents) > 2:
        _add_reason(reasons, "participant_count_not_two")

    for wrapper in raw_opponents:
        if not isinstance(wrapper, Mapping):
            _add_reason(reasons, "participant_name_missing")
            continue
        team = wrapper.get("opponent", _MISSING)
        if not isinstance(team, Mapping):
            _add_reason(reasons, "participant_name_missing")
            continue
        facts.append(
            _participant_fact(
                source="pandascore",
                side=None,
                team=team,
                name_path="name",
                team_id_path="id",
                reasons=reasons,
            )
        )
    return facts, len(raw_opponents)


def _opendota_participants(
    candidate_detail: Mapping[str, JsonValue],
    reasons: list[str],
) -> list[ParticipantFact]:
    facts: list[ParticipantFact] = []
    for side in ("radiant", "dire"):
        team_field = f"{side}_team"
        team = candidate_detail.get(team_field, _MISSING)
        if not isinstance(team, Mapping):
            team_mapping: Mapping[str, JsonValue] = {}
            _add_reason(reasons, "participant_name_missing")
        else:
            team_mapping = team
        root_id_field = f"{side}_team_id"
        if root_id_field in candidate_detail:
            team_id = candidate_detail[root_id_field]
            team_id_present = True
            team_id_path = root_id_field
        else:
            team_id, team_id_present = _read(team_mapping, "team_id")
            team_id_path = f"{team_field}.team_id" if team_id_present else None
        if not team_id_present:
            team_id = None
        facts.append(
            _participant_fact(
                source="opendota",
                side=side,
                team=team_mapping,
                name_path="name",
                team_id_path="id",
                reasons=reasons,
                team_id_override=(team_id, team_id_present, team_id_path),
            )
        )
    return facts


def _participant_fact(
    *,
    source: Literal["pandascore", "opendota"],
    side: Side | None,
    team: Mapping[str, JsonValue],
    name_path: str,
    team_id_path: str,
    reasons: list[str],
    team_id_override: tuple[JsonValue | None, bool, str | None] | None = None,
) -> ParticipantFact:
    if team_id_override is None:
        team_id, team_id_present = _read(team, team_id_path)
        stored_team_id_path = team_id_path if team_id_present else None
    else:
        team_id, team_id_present, stored_team_id_path = team_id_override

    name, name_present = _read(team, name_path)
    normalized_name: str | None = None
    if not name_present or name is None:
        _add_reason(reasons, "participant_name_missing")
    elif not isinstance(name, str):
        _add_reason(reasons, "participant_name_not_comparable")
    else:
        normalized_name = _normalize_name(name)
        if not normalized_name:
            _add_reason(reasons, "participant_name_not_comparable")
            normalized_name = None

    return ParticipantFact(
        source=source,
        side=side,
        team_id=team_id if team_id_present else None,
        team_id_present=team_id_present,
        team_id_path=stored_team_id_path,
        name=name if name_present else None,
        name_present=name_present,
        normalized_name=normalized_name,
    )


def _compare_participants(
    pandascore: list[ParticipantFact],
    pandascore_opponent_count: int,
    opendota: list[ParticipantFact],
    reasons: list[str],
) -> tuple[EvidenceStatus, list[ParticipantAssociation]]:
    if pandascore_opponent_count != 2 or len(pandascore) != 2 or len(opendota) != 2:
        if pandascore_opponent_count > 2:
            _add_reason(reasons, "participant_count_not_two")
        else:
            _add_reason(reasons, "participant_name_missing")
        return "unknown", []

    pscore_names = [item.normalized_name for item in pandascore]
    opendota_names = [item.normalized_name for item in opendota]
    if any(name is None for name in (*pscore_names, *opendota_names)):
        return "unknown", []

    if len(set(pscore_names)) != 2 or len(set(opendota_names)) != 2:
        _add_reason(reasons, "participant_name_collision")
        return "unknown", []

    matching_names = pscore_names, opendota_names
    if set(pscore_names) != set(opendota_names):
        pscore_keys = [_without_common_suffix(item.name) for item in pandascore]
        opendota_keys = [_without_common_suffix(item.name) for item in opendota]
        if not all((*pscore_keys, *opendota_keys)):
            _add_reason(reasons, "participant_names_unaligned")
            return "unknown", []
        if len(set(pscore_keys)) != 2 or len(set(opendota_keys)) != 2:
            _add_reason(reasons, "participant_name_collision")
            return "unknown", []
        if set(pscore_keys) != set(opendota_keys):
            _add_reason(reasons, "participant_names_unaligned")
            return "unknown", []
        matching_names = pscore_keys, opendota_keys

    opendota_by_name = dict(zip(matching_names[1], opendota, strict=True))
    associations: list[ParticipantAssociation] = []
    for key, team in zip(matching_names[0], pandascore, strict=True):
        counterpart = opendota_by_name[key]
        associations.append(
            ParticipantAssociation(
                pandascore_team_id=_positive_int(team.team_id),
                opendota_side=counterpart.side,  # type: ignore[arg-type]
                opendota_team_id=_positive_int(counterpart.team_id),
                pandascore_name=team.name,  # type: ignore[arg-type]
                opendota_name=counterpart.name,  # type: ignore[arg-type]
                name_match_method=(
                    "normalized_exact"
                    if team.normalized_name == counterpart.normalized_name
                    else "common_suffix"
                ),
            )
        )
    return "supported", associations


def _compare_winner(
    winner: JsonValue | None,
    winner_present: bool,
    winner_id_field: JsonValue | None,
    winner_id_field_present: bool,
    winner_type_field: JsonValue | None,
    winner_type_field_present: bool,
    radiant_win: JsonValue | None,
    radiant_win_present: bool,
    participants_status: EvidenceStatus,
    pandascore_participants: list[ParticipantFact],
    associations: list[ParticipantAssociation],
    reasons: list[str],
) -> WinnerStatus:
    if not winner_present or not isinstance(winner, Mapping):
        _add_reason(reasons, "game_winner_missing")
        return "unknown"

    winner_id = winner.get("id")
    if type(winner_id) is not int or winner_id <= 0:
        _add_reason(reasons, "game_winner_missing")
        return "unknown"

    if winner_id_field_present and winner_id_field is not None:
        if type(winner_id_field) is not int or winner_id_field != winner_id:
            _add_reason(reasons, "game_winner_source_conflict")
            return "unknown"

    nested_winner_type, nested_winner_type_present = _read(winner, "type")
    explicit_types = [
        value
        for value, present in (
            (winner_type_field, winner_type_field_present),
            (nested_winner_type, nested_winner_type_present),
        )
        if present and value is not None
    ]
    if len(explicit_types) == 2 and explicit_types[0] != explicit_types[1]:
        _add_reason(reasons, "game_winner_source_conflict")
        return "unknown"
    if not explicit_types:
        _add_reason(reasons, "game_winner_type_missing")
        return "unknown"
    if any(value != "Team" for value in explicit_types):
        _add_reason(reasons, "game_winner_not_team")
        return "unknown"

    source_participants = [
        participant
        for participant in pandascore_participants
        if _positive_int(participant.team_id) == winner_id
    ]
    if not source_participants:
        _add_reason(
            reasons,
            "winner_participants_unavailable"
            if len(pandascore_participants) != 2
            or any(_positive_int(item.team_id) is None for item in pandascore_participants)
            else "game_winner_not_in_participants",
        )
        return "unknown"
    if len(source_participants) > 1:
        _add_reason(reasons, "game_winner_participant_ambiguous")
        return "unknown"

    if participants_status != "supported":
        _add_reason(reasons, "winner_participants_unavailable")
        return "unknown"

    if not radiant_win_present or type(radiant_win) is not bool:
        _add_reason(reasons, "opendota_winner_missing")
        return "unknown"

    winner_associations = [
        association
        for association in associations
        if association.pandascore_team_id == winner_id
    ]
    if len(winner_associations) != 1:
        _add_reason(reasons, "game_winner_not_in_participants")
        return "unknown"

    opendota_winner_side: Side = "radiant" if radiant_win else "dire"
    if winner_associations[0].opendota_side == opendota_winner_side:
        return "consistent"
    return "conflict"


def _normalize_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _without_common_suffix(name: JsonValue | None) -> str | None:
    if not isinstance(name, str):
        return None
    normalized = unicodedata.normalize("NFKC", name).casefold().strip()
    return _normalize_name(_COMMON_TEAM_SUFFIX.sub("", normalized)) or None


def _positive_int(value: JsonValue | None) -> int | None:
    return value if type(value) is int and value > 0 else None


def _read(
    record: Mapping[str, JsonValue],
    field: str,
) -> tuple[JsonValue | None, bool]:
    if field not in record:
        return None, False
    return record[field], True


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


__all__ = [
    "GameIdentityEvidence",
    "GameIdentityFacts",
    "ParticipantAssociation",
    "ParticipantFact",
    "compare_game_identity_evidence",
]
