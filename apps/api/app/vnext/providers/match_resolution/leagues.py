"""Offline League-candidate discovery from PandaScore competition context."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue

LeagueCandidateCategory = Literal[
    "candidates_found",
    "no_candidates",
    "insufficient_context",
    "candidate_limit_exceeded",
]
ComparisonStatus = Literal["matched", "conflicting", "unspecified"]
JsonObject = dict[str, JsonValue]
ComparableValue = int | tuple[int, int] | None


@dataclass(frozen=True)
class LeagueFieldComparison:
    """Explicit season or year comparison; unknown formats stay unspecified."""

    status: ComparisonStatus
    pandascore_value: ComparableValue
    opendota_value: ComparableValue


@dataclass(frozen=True)
class LeagueCandidate:
    """One OpenDota League record retained as a possible search scope."""

    record: Mapping[str, JsonValue]
    opendota_name: str
    matched_brand_terms: tuple[str, ...]
    season_comparison: LeagueFieldComparison
    year_comparison: LeagueFieldComparison
    pandascore_fields: JsonObject


@dataclass(frozen=True)
class LeagueCandidateResult:
    """A bounded League search scope, never a cross-source identity claim."""

    category: LeagueCandidateCategory
    candidates: tuple[LeagueCandidate, ...]
    total_candidate_count: int
    reason: str | None


def find_league_candidates(
    match_context: Mapping[str, JsonValue],
    opendota_leagues: Sequence[Mapping[str, JsonValue]],
    *,
    max_candidates: int,
) -> LeagueCandidateResult:
    """Find a bounded, explainable OpenDota League scope from explicit names.

    Only ``league.name`` is used to find the competition brand. Season and year
    facts can exclude an explicit conflict, but missing or unrecognized values
    never remove a brand match. The function is synchronous and performs no I/O.
    """

    if type(max_candidates) is not int or max_candidates <= 0:
        raise ValueError("max_candidates must be a positive integer")

    if not isinstance(match_context, Mapping):
        return _empty_result("insufficient_context", "match_context_invalid")
    if not isinstance(opendota_leagues, Sequence) or isinstance(
        opendota_leagues, (str, bytes, bytearray)
    ):
        raise ValueError("opendota_leagues must be a sequence")

    source_fields = _pandascore_source_fields(match_context)
    league_value = match_context.get("league")
    if not isinstance(league_value, Mapping):
        reason = "league_missing" if "league" not in match_context else "league_invalid"
        return _empty_result("insufficient_context", reason)

    league_name = league_value.get("name")
    if not isinstance(league_name, str):
        reason = "league_name_missing" if "name" not in league_value else "league_name_invalid"
        return _empty_result("insufficient_context", reason)
    brand_terms = _tokens(league_name)
    if not brand_terms:
        return _empty_result("insufficient_context", "league_name_unsearchable")

    serie_value = match_context.get("serie")
    season_source = (
        serie_value.get("season") if isinstance(serie_value, Mapping) else None
    )
    year_source = serie_value.get("year") if isinstance(serie_value, Mapping) else None
    pandascore_season = _parse_pandascore_season(season_source)
    pandascore_year = _parse_pandascore_year(year_source)

    candidates: list[LeagueCandidate] = []
    conflicting_count = 0
    for record in opendota_leagues:
        if not isinstance(record, Mapping):
            continue
        opendota_name = record.get("name")
        if not isinstance(opendota_name, str):
            continue

        name_tokens = _tokens(opendota_name)
        brand_positions = _subsequence_positions(name_tokens, brand_terms)
        if not brand_positions:
            continue
        opendota_season = _parse_opendota_season(
            name_tokens,
            brand_positions,
            brand_width=len(brand_terms),
        )
        opendota_year = _parse_year_range(opendota_name)
        season_comparison = _compare_values(
            pandascore_season,
            opendota_season,
            _same_integer,
        )
        year_comparison = _compare_values(
            pandascore_year,
            opendota_year,
            _ranges_overlap,
        )
        if (
            season_comparison.status == "conflicting"
            or year_comparison.status == "conflicting"
        ):
            conflicting_count += 1
            continue

        candidates.append(
            LeagueCandidate(
                record=record,
                opendota_name=opendota_name,
                matched_brand_terms=brand_terms,
                season_comparison=season_comparison,
                year_comparison=year_comparison,
                pandascore_fields=source_fields,
            )
        )

    total = len(candidates)
    if total > max_candidates:
        return LeagueCandidateResult(
            category="candidate_limit_exceeded",
            candidates=(),
            total_candidate_count=total,
            reason="candidate_budget_exceeded",
        )
    if candidates:
        return LeagueCandidateResult(
            category="candidates_found",
            candidates=tuple(candidates),
            total_candidate_count=total,
            reason=None,
        )

    reason = "all_brand_candidates_conflict" if conflicting_count else "brand_not_found"
    return LeagueCandidateResult(
        category="no_candidates",
        candidates=(),
        total_candidate_count=0,
        reason=reason,
    )


def _pandascore_source_fields(match_context: Mapping[str, JsonValue]) -> JsonObject:
    fields: JsonObject = {}
    league = match_context.get("league")
    if "league" in match_context:
        if isinstance(league, Mapping):
            fields["league"] = (
                {"name": league["name"]} if "name" in league else {}
            )
        else:
            fields["league"] = league

    serie = match_context.get("serie")
    if "serie" in match_context:
        if isinstance(serie, Mapping):
            fields["serie"] = {
                key: serie[key]
                for key in ("name", "full_name", "season", "year")
                if key in serie
            }
        else:
            fields["serie"] = serie
    return fields


def _tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return tuple(re.findall(r"[^\W_]+", normalized, flags=re.UNICODE))


def _subsequence_positions(
    tokens: tuple[str, ...], brand_terms: tuple[str, ...]
) -> tuple[int, ...]:
    width = len(brand_terms)
    if not width or width > len(tokens):
        return ()
    return tuple(
        index
        for index in range(len(tokens) - width + 1)
        if tokens[index : index + width] == brand_terms
    )


def _parse_pandascore_season(value: JsonValue | None) -> int | None:
    if type(value) is int:
        return value if 0 < value < 1000 else None
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    match = re.fullmatch(r"(?:season\s+)?([0-9]{1,3})", normalized)
    if match is None:
        return None
    season = int(match.group(1))
    return season if season > 0 else None


def _parse_pandascore_year(value: JsonValue | None) -> tuple[int, int] | None:
    if type(value) is int:
        return (value, value) if 1000 <= value <= 9999 else None
    if not isinstance(value, str):
        return None
    return _parse_year_range(value)


def _parse_opendota_season(
    tokens: tuple[str, ...],
    brand_positions: tuple[int, ...],
    *,
    brand_width: int,
) -> int | None:
    has_season_marker = False
    invalid_season_marker = False
    marker_values: set[int] = set()
    for index, token in enumerate(tokens[:-1]):
        if token != "season":
            continue
        has_season_marker = True
        next_token = tokens[index + 1]
        if re.fullmatch(r"[0-9]{1,3}", next_token):
            value = int(next_token)
            if value > 0:
                marker_values.add(value)
            else:
                invalid_season_marker = True
        else:
            invalid_season_marker = True
    if has_season_marker:
        if invalid_season_marker:
            return None
        return next(iter(marker_values)) if len(marker_values) == 1 else None
    if len(brand_positions) != 1:
        return None

    after_brand = brand_positions[0] + brand_width
    if after_brand >= len(tokens):
        return None
    return _parse_canonical_roman(tokens[after_brand])


def _parse_canonical_roman(token: str) -> int | None:
    if not re.fullmatch(r"[ivxlcdm]+", token):
        return None
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total = 0
    for index, char in enumerate(token):
        current = values[char]
        following = values[token[index + 1]] if index + 1 < len(token) else 0
        total += -current if current < following else current
    if not 0 < total <= 3999 or _to_roman(total) != token:
        return None
    return total


def _to_roman(value: int) -> str:
    numerals = (
        (1000, "m"),
        (900, "cm"),
        (500, "d"),
        (400, "cd"),
        (100, "c"),
        (90, "xc"),
        (50, "l"),
        (40, "xl"),
        (10, "x"),
        (9, "ix"),
        (5, "v"),
        (4, "iv"),
        (1, "i"),
    )
    output: list[str] = []
    for amount, numeral in numerals:
        count, value = divmod(value, amount)
        output.extend([numeral] * count)
    return "".join(output)


def _parse_year_range(value: str) -> tuple[int, int] | None:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    range_matches = list(
        re.finditer(r"(?<!\d)(\d{4})\s*[-–—]\s*(\d{4})(?!\d)", normalized)
    )
    if len(range_matches) > 1:
        return None
    if range_matches:
        match = range_matches[0]
        start, end = int(match.group(1)), int(match.group(2))
        if start > end:
            return None
        remainder = normalized[: match.start()] + normalized[match.end() :]
        if re.search(r"(?<!\d)\d{4}(?!\d)", remainder):
            return None
        return start, end

    years = {
        int(match.group(0))
        for match in re.finditer(r"(?<!\d)\d{4}(?!\d)", normalized)
    }
    if len(years) != 1:
        return None
    year = years.pop()
    return year, year


def _compare_values(
    pandascore_value: ComparableValue,
    opendota_value: ComparableValue,
    matches: Callable[[ComparableValue, ComparableValue], bool],
) -> LeagueFieldComparison:
    if pandascore_value is None or opendota_value is None:
        status: ComparisonStatus = "unspecified"
    elif matches(pandascore_value, opendota_value):
        status = "matched"
    else:
        status = "conflicting"
    return LeagueFieldComparison(
        status=status,
        pandascore_value=pandascore_value,
        opendota_value=opendota_value,
    )


def _same_integer(left: ComparableValue, right: ComparableValue) -> bool:
    return isinstance(left, int) and isinstance(right, int) and left == right


def _ranges_overlap(left: ComparableValue, right: ComparableValue) -> bool:
    return (
        isinstance(left, tuple)
        and isinstance(right, tuple)
        and max(left[0], right[0]) <= min(left[1], right[1])
    )


def _empty_result(
    category: Literal["insufficient_context"], reason: str
) -> LeagueCandidateResult:
    return LeagueCandidateResult(
        category=category,
        candidates=(),
        total_candidate_count=0,
        reason=reason,
    )


__all__ = [
    "ComparisonStatus",
    "LeagueCandidate",
    "LeagueCandidateCategory",
    "LeagueCandidateResult",
    "LeagueFieldComparison",
    "find_league_candidates",
]
