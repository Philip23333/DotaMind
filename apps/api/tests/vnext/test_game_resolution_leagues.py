from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.vnext.providers.match_resolution import find_league_candidates

_MISSING = object()


def _context(
    league_name: Any = "DreamLeague",
    *,
    serie_name: Any = "China Closed Qualifier",
    full_name: Any = _MISSING,
    season: Any = _MISSING,
    year: Any = _MISSING,
) -> dict[str, Any]:
    league = {"name": league_name, "provider_extension": {"keep": True}}
    serie: dict[str, Any] = {}
    for key, value in (
        ("name", serie_name),
        ("full_name", full_name),
        ("season", season),
        ("year", year),
    ):
        if value is not _MISSING:
            serie[key] = value
    return {
        "id": 1745472,
        "league": league,
        "serie": serie,
        "match_extension": {"unchanged": [1, 2]},
    }


def _league(league_id: int, name: str, **extra: Any) -> dict[str, Any]:
    return {"leagueid": league_id, "name": name, **extra}


@pytest.mark.parametrize(
    (
        "context",
        "leagues",
        "expected_id",
        "season_status",
        "year_status",
    ),
    [
        (
            _context(
                "BLAST Slam",
                serie_name="",
                full_name="Season 8 2026",
                season="8",
                year=2026,
            ),
            [_league(19102, "BLAST SLAM VIII")],
            19102,
            "matched",
            "unspecified",
        ),
        (
            _context(
                "DreamLeague",
                serie_name="China Closed Qualifier",
                full_name="China Closed Qualifier season 30 2026",
                season="30",
                year=2026,
            ),
            [_league(20359, "DreamLeague Season 30 Qualifiers")],
            20359,
            "matched",
            "unspecified",
        ),
        (
            _context(
                "EPL Masters",
                serie_name="Play-In",
                full_name="Play-In season 3 2026",
                season="3",
                year=2026,
            ),
            [_league(19944, "EPL Masters 2026")],
            19944,
            "unspecified",
            "matched",
        ),
        (
            _context(
                "DreamLeague",
                serie_name="Western Europe Open Qualifier 2",
                full_name="Western Europe Open Qualifier 2 2026",
                season=None,
                year=2026,
            ),
            [_league(20359, "DreamLeague Season 30 Qualifiers")],
            20359,
            "unspecified",
            "unspecified",
        ),
    ],
)
def test_historical_competition_context_produces_search_scope(
    context: dict[str, Any],
    leagues: list[dict[str, Any]],
    expected_id: int,
    season_status: str,
    year_status: str,
) -> None:
    result = find_league_candidates(context, leagues, max_candidates=4)

    assert result.category == "candidates_found"
    assert result.total_candidate_count == 1
    assert [candidate.record["leagueid"] for candidate in result.candidates] == [
        expected_id
    ]
    candidate = result.candidates[0]
    assert candidate.season_comparison.status == season_status
    assert candidate.year_comparison.status == year_status
    assert candidate.record is leagues[0]


def test_roman_edition_nfkc_case_and_punctuation_are_normalized() -> None:
    context = _context("BLAST Slam", season=8, year=2026)
    leagues = [_league(19102, "  ＢＬＡＳＴ—SLAM VIII 2026 ")]

    result = find_league_candidates(context, leagues, max_candidates=2)

    assert result.category == "candidates_found"
    candidate = result.candidates[0]
    assert candidate.matched_brand_terms == ("blast", "slam")
    assert candidate.season_comparison.pandascore_value == 8
    assert candidate.season_comparison.opendota_value == 8
    assert candidate.season_comparison.status == "matched"
    assert candidate.year_comparison.status == "matched"


def test_full_brand_tokens_match_but_substrings_and_series_words_do_not() -> None:
    context = _context(
        "EPL",
        serie_name="DreamLeague Western Europe Open Qualifier 2",
        full_name="EPL Masters",
        season=3,
    )
    leagues = [
        _league(101, "NotEPL Masters"),
        _league(102, "Western Europe Open Qualifier 2"),
        _league(103, "EPL-Masters"),
    ]

    result = find_league_candidates(context, leagues, max_candidates=2)

    assert result.category == "candidates_found"
    assert [candidate.record["leagueid"] for candidate in result.candidates] == [
        103
    ]


def test_qualifier_number_is_not_used_as_season() -> None:
    context = _context(
        "DreamLeague",
        serie_name="China Closed Qualifier",
        season=30,
    )
    result = find_league_candidates(
        context,
        [_league(20359, "DreamLeague Season 30 Qualifiers 2")],
        max_candidates=1,
    )

    assert result.category == "candidates_found"
    assert result.candidates[0].season_comparison.status == "matched"
    assert result.candidates[0].season_comparison.opendota_value == 30


def test_explicit_season_and_year_conflicts_are_excluded_but_missing_are_kept() -> None:
    context = _context("DreamLeague", season=30, year=2026)
    leagues = [
        _league(20359, "DreamLeague Season 29 Qualifiers 2026"),
        _league(20360, "DreamLeague Season 30 Qualifiers 2025"),
        _league(20361, "DreamLeague Season 30 Qualifiers"),
        _league(20362, "DreamLeague Qualifiers 2026"),
    ]

    result = find_league_candidates(context, leagues, max_candidates=3)

    assert result.category == "candidates_found"
    assert [candidate.record["leagueid"] for candidate in result.candidates] == [
        20361,
        20362,
    ]
    assert result.candidates[0].season_comparison.status == "matched"
    assert result.candidates[0].year_comparison.status == "unspecified"
    assert result.candidates[1].season_comparison.status == "unspecified"
    assert result.candidates[1].year_comparison.status == "matched"


def test_explicit_year_range_matches_and_four_digit_season_is_not_edition() -> None:
    year_context = _context("EPL", season=3, year=2026)
    year_result = find_league_candidates(
        year_context,
        [_league(19944, "EPL Masters 2025–2026")],
        max_candidates=1,
    )
    four_digit_season = _context("DreamLeague", season=2026)
    season_result = find_league_candidates(
        four_digit_season,
        [_league(20359, "DreamLeague Season 30 Qualifiers")],
        max_candidates=1,
    )

    assert year_result.candidates[0].year_comparison.status == "matched"
    assert year_result.candidates[0].year_comparison.opendota_value == (2025, 2026)
    assert season_result.category == "candidates_found"
    assert season_result.candidates[0].season_comparison.status == "unspecified"


def test_annual_league_does_not_require_a_pandascore_season() -> None:
    context = _context("EPL", season=_MISSING, year=2026)

    result = find_league_candidates(
        context,
        [_league(19944, "EPL Masters 2026")],
        max_candidates=1,
    )

    assert result.category == "candidates_found"
    assert result.candidates[0].season_comparison.status == "unspecified"
    assert result.candidates[0].year_comparison.status == "matched"


def test_unrecognized_pandascore_season_format_remains_unspecified() -> None:
    context = _context("DreamLeague", season="thirty")

    result = find_league_candidates(
        context,
        [_league(20359, "DreamLeague Season 30 Qualifiers")],
        max_candidates=1,
    )

    assert result.category == "candidates_found"
    assert result.candidates[0].season_comparison.status == "unspecified"
    assert result.candidates[0].season_comparison.pandascore_value is None


@pytest.mark.parametrize("season", [0, "0", "000", "Season 0"])
def test_zero_pandascore_season_is_not_a_valid_conflict(season: Any) -> None:
    context = _context("DreamLeague", season=season)

    result = find_league_candidates(
        context,
        [_league(20359, "DreamLeague Season 30 Qualifiers")],
        max_candidates=1,
    )

    assert result.category == "candidates_found"
    assert result.candidates[0].season_comparison.status == "unspecified"
    assert result.candidates[0].season_comparison.pandascore_value is None


def test_western_europe_missing_season_keeps_all_brand_candidates_and_enforces_budget() -> None:
    context = _context(
        "DreamLeague",
        serie_name="Western Europe Open Qualifier 2",
        season=None,
    )
    leagues = [
        _league(21000, "DreamLeague Season 29 Qualifiers"),
        _league(20359, "DreamLeague Season 30 Qualifiers"),
    ]

    result = find_league_candidates(context, leagues, max_candidates=2)
    limited = find_league_candidates(context, leagues, max_candidates=1)

    assert result.category == "candidates_found"
    assert result.total_candidate_count == 2
    assert [candidate.record["leagueid"] for candidate in result.candidates] == [
        21000,
        20359,
    ]
    assert all(
        candidate.season_comparison.status == "unspecified"
        and candidate.season_comparison.pandascore_value is None
        for candidate in result.candidates
    )
    assert limited.category == "candidate_limit_exceeded"
    assert limited.reason == "candidate_budget_exceeded"
    assert limited.total_candidate_count == 2
    assert limited.candidates == ()


def test_context_without_searchable_league_name_is_insufficient() -> None:
    contexts = [
        {"serie": {"full_name": "DreamLeague Season 30"}},
        _context(None),
        _context(" !!! "),
    ]

    for context in contexts:
        result = find_league_candidates(
            context,
            [_league(20359, "DreamLeague Season 30 Qualifiers")],
            max_candidates=1,
        )
        assert result.category == "insufficient_context"
        assert result.total_candidate_count == 0
        assert result.candidates == ()


def test_no_brand_candidate_and_all_explicit_conflicts_are_distinct_reasons() -> None:
    context = _context("DreamLeague", season=30)

    no_brand = find_league_candidates(
        context,
        [_league(1, "EPL Masters 2026")],
        max_candidates=1,
    )
    conflict = find_league_candidates(
        context,
        [_league(20359, "DreamLeague Season 29 Qualifiers")],
        max_candidates=1,
    )

    assert no_brand.category == "no_candidates"
    assert no_brand.reason == "brand_not_found"
    assert conflict.category == "no_candidates"
    assert conflict.reason == "all_brand_candidates_conflict"


def test_source_fields_and_raw_league_records_are_preserved_without_mutation() -> None:
    context = _context(
        "DreamLeague",
        serie_name="Western Europe Open Qualifier 2",
        full_name="DreamLeague: Western Europe Open Qualifier 2",
        season=None,
    )
    record = _league(
        20359,
        "DreamLeague Season 30 Qualifiers",
        future_field={"kept": [1, None]},
    )
    before = deepcopy((context, record))

    result = find_league_candidates(context, [record], max_candidates=2)

    assert (context, record) == before
    candidate = result.candidates[0]
    assert candidate.record == record
    assert candidate.record["future_field"] == {"kept": [1, None]}
    assert candidate.pandascore_fields == {
        "league": {"name": "DreamLeague"},
        "serie": {
            "name": "Western Europe Open Qualifier 2",
            "full_name": "DreamLeague: Western Europe Open Qualifier 2",
            "season": None,
        },
    }
    assert "year" not in candidate.pandascore_fields["serie"]
    assert candidate.season_comparison.status == "unspecified"
    assert candidate.season_comparison.opendota_value == 30


@pytest.mark.parametrize("max_candidates", [True, False, 0, -1, 1.0, "2", None])
def test_candidate_budget_must_be_a_strict_positive_integer(
    max_candidates: Any,
) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        find_league_candidates(
            _context(),
            [_league(20359, "DreamLeague Season 30 Qualifiers")],
            max_candidates=max_candidates,
        )
