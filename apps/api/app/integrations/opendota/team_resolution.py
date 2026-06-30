import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Literal

from app.core.config import get_policy

TeamResolutionStatus = Literal["resolved", "ambiguous", "not_found"]


@dataclass(frozen=True)
class TeamResolution:
    status: TeamResolutionStatus
    requested_name: str
    team: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)


def resolve_team(requested_name: str, teams: list[dict[str, Any]]) -> TeamResolution:
    query_variants = _team_query_variants(requested_name)
    if not query_variants:
        return TeamResolution("not_found", requested_name)

    exact_matches: list[dict[str, Any]] = []
    for team in teams:
        score, reason = _exact_team_score(query_variants, team)
        if score > 0:
            exact_matches.append(_team_candidate(team, score, reason))

    if exact_matches:
        return _select_team_resolution(requested_name, exact_matches, teams)

    fuzzy_matches = []
    primary_query = query_variants[0][0]
    cutoff = get_policy().team_report.resolution.fuzzy_score_cutoff
    for team in teams:
        score, reason = _fuzzy_team_score(primary_query, team)
        if score >= cutoff:
            fuzzy_matches.append(_team_candidate(team, score, reason))

    if not fuzzy_matches:
        return TeamResolution("not_found", requested_name)
    return _select_team_resolution(requested_name, fuzzy_matches, teams)


def _select_team_resolution(
    requested_name: str,
    matches: list[dict[str, Any]],
    teams: list[dict[str, Any]],
) -> TeamResolution:
    matches.sort(
        key=lambda item: (
            float(item["match_score"]),
            int(item.get("last_match_time") or 0),
            float(item.get("rating") or 0),
        ),
        reverse=True,
    )
    best_score = float(matches[0]["match_score"])
    resolution_policy = get_policy().team_report.resolution
    plausible = [
        item
        for item in matches
        if best_score - float(item["match_score"])
        <= resolution_policy.ambiguity_score_delta
    ]
    if len(plausible) > 1:
        return TeamResolution(
            "ambiguous",
            requested_name,
            candidates=plausible[: resolution_policy.candidate_limit],
        )

    team_id = plausible[0]["team_id"]
    selected = next(team for team in teams if team.get("team_id") == team_id)
    return TeamResolution(
        "resolved",
        requested_name,
        team=selected,
        candidates=plausible,
    )


def _exact_team_score(
    query_variants: list[tuple[str, float, str]],
    team: dict[str, Any],
) -> tuple[float, str]:
    name_variants = _team_value_variants(str(team.get("name") or ""))
    tag_variants = _team_value_variants(str(team.get("tag") or ""))
    best = (0.0, "")
    for query, weight, query_reason in query_variants:
        if query in name_variants:
            name_weight = weight + 5.0 if query_reason == "exact" else weight
            if name_weight > best[0]:
                best = (name_weight, f"{query_reason} matched team name")
        if query in tag_variants and weight > best[0]:
            best = (weight, f"{query_reason} matched team tag")
    return best


def _fuzzy_team_score(query: str, team: dict[str, Any]) -> tuple[float, str]:
    name_variants = _team_value_variants(str(team.get("name") or ""))
    tag_variants = _team_value_variants(str(team.get("tag") or ""))
    name_score = max(
        (
            SequenceMatcher(None, query, value).ratio() * 70 + 5
            for value in name_variants
        ),
        default=0.0,
    )
    tag_score = max(
        (SequenceMatcher(None, query, value).ratio() * 70 for value in tag_variants),
        default=0.0,
    )
    if name_score >= tag_score:
        return round(name_score, 2), "fuzzy team name match"
    return round(tag_score, 2), "fuzzy team tag match"


def _team_query_variants(value: str) -> list[tuple[str, float, str]]:
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value.strip())
    normalized = _normalize_team_value(expanded)
    if not normalized:
        return []

    tokens = normalized.split()
    generic_words = set(get_policy().team_report.resolution.generic_words)
    stripped_tokens = [token for token in tokens if token not in generic_words]
    stripped = " ".join(stripped_tokens) or normalized
    candidates = [
        (normalized, 100.0, "exact"),
        (stripped, 95.0, "normalized"),
        (stripped.replace(" ", ""), 90.0, "compact"),
    ]
    if len(stripped_tokens) > 1:
        candidates.append(
            ("".join(token[0] for token in stripped_tokens), 75.0, "acronym")
        )

    deduplicated: dict[str, tuple[float, str]] = {}
    for candidate, weight, reason in candidates:
        if candidate and weight > deduplicated.get(candidate, (0.0, ""))[0]:
            deduplicated[candidate] = (weight, reason)
    return [
        (candidate, weight, reason)
        for candidate, (weight, reason) in deduplicated.items()
    ]


def _team_value_variants(value: str) -> set[str]:
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value.strip())
    normalized = _normalize_team_value(expanded)
    if not normalized:
        return set()
    tokens = normalized.split()
    generic_words = set(get_policy().team_report.resolution.generic_words)
    stripped = " ".join(token for token in tokens if token not in generic_words)
    return {
        variant
        for variant in (normalized, stripped, stripped.replace(" ", ""))
        if variant
    }


def _normalize_team_value(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _team_candidate(team: dict[str, Any], score: float, reason: str) -> dict[str, Any]:
    return {
        "team_id": team.get("team_id"),
        "name": team.get("name"),
        "tag": team.get("tag"),
        "rating": team.get("rating"),
        "last_match_time": team.get("last_match_time"),
        "match_score": round(score, 2),
        "match_reason": reason,
    }
