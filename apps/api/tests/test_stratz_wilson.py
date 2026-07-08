import math

import pytest

from app.integrations.stratz.wilson import DEFAULT_Z, wilson_lower_bound

# --- defaults / assumptions ---


def test_default_z_is_95_percent_ci() -> None:
    # STRATZ does not publish z; we assume 95% CI. Pin the constant so any
    # change is deliberate and visible in provenance.
    assert DEFAULT_Z == pytest.approx(1.96)


# --- edge cases (fail loud on bad input, well-defined on no data) ---


def test_no_matches_returns_zero() -> None:
    assert wilson_lower_bound(0, 0) == 0.0


def test_zero_wins_returns_zero() -> None:
    # p=0 -> lower bound is exactly 0.
    assert wilson_lower_bound(0, 1000) == 0.0


def test_perfect_record_stays_below_one() -> None:
    # Undefeated over a FINITE sample still carries a confidence penalty, so
    # the lower bound is high but strictly < 1 (unlike raw win rate).
    score = wilson_lower_bound(1000, 1000)
    assert 0.95 < score < 1.0


def test_invalid_counts_raise() -> None:
    with pytest.raises(ValueError):
        wilson_lower_bound(-1, 10)
    with pytest.raises(ValueError):
        wilson_lower_bound(11, 10)  # wins > n
    with pytest.raises(ValueError):
        wilson_lower_bound(5, -1)


def test_invalid_z_raises() -> None:
    with pytest.raises(ValueError):
        wilson_lower_bound(5, 10, z=-1.0)


# --- core invariant: never exceeds the observed proportion ---


def test_lower_bound_never_exceeds_proportion() -> None:
    # Mathematically the lower bound is always <= p (proven for z >= 0, n > 0);
    # +1e-12 guards the last float ULP.
    for wins, n in [(1, 2), (1, 100), (550, 1000), (9999, 10000)]:
        assert wilson_lower_bound(wins, n) <= wins / n + 1e-12


# --- the whole point: sample-size awareness ---


def test_more_samples_at_same_win_rate_scores_higher() -> None:
    # Same 55% win rate, 10x the sample -> more confidence -> higher rating.
    small = wilson_lower_bound(55, 100)
    large = wilson_lower_bound(5500, 10000)
    assert large > small


def test_more_wins_at_same_sample_scores_higher() -> None:
    n = 1000
    assert wilson_lower_bound(600, n) > wilson_lower_bound(550, n)
    assert wilson_lower_bound(550, n) > wilson_lower_bound(500, n)


def test_high_winrate_tiny_sample_ranks_below_modest_winrate_huge_sample() -> None:
    # The case raw win-rate ranking gets wrong and Wilson fixes: a 60% hero
    # over only 10 games is NOT more trustworthy than a 55.6% hero over 880k.
    fluke = wilson_lower_bound(6, 10)            # 60% over 10
    wraith_king = wilson_lower_bound(490326, 882600)  # ~55.6% over 882.6k
    assert wraith_king > fluke
    assert fluke < 0.5  # 60% over 10 games is below even a coin-flip hero


def test_converges_to_proportion_as_sample_grows() -> None:
    # The z-penalty shrinks as n grows, so the lower bound approaches the true
    # win rate and the gap tightens monotonically. Small n is DELIBERATELY far
    # from p (0.098 at n=100) — that penalty is the entire point of the score.
    p = 0.55
    gaps = [abs(wilson_lower_bound(round(p * n), n) - p) for n in (100, 1_000, 10_000, 100_000)]
    assert gaps == sorted(gaps, reverse=True)  # strictly decreasing
    assert gaps[-1] < 0.01                      # large n -> essentially p


# --- numeric cross-check (independent of the implementation's algebra) ---


def test_known_value_matches_normal_approximation_closely() -> None:
    # Wilson lower bound ≈ p - z*sqrt(p(1-p)/n) for large n (Agresti-Coull
    # neighbourhood). Independent formula -> non-circular check.
    wins, n, z = 5500, 10000, 1.96
    p = wins / n
    normal_approx = p - z * math.sqrt(p * (1 - p) / n)
    assert wilson_lower_bound(wins, n, z) == pytest.approx(normal_approx, abs=2e-4)


def test_known_value_is_pinned() -> None:
    # Hard pin (computed independently of this module) catches sign/formula typos.
    assert wilson_lower_bound(5500, 10000) == pytest.approx(0.5402, abs=1e-3)


# --- regression: reproduces STRATZ trends top-of-table ordering ---


def test_reproduces_stratz_trends_top2_order() -> None:
    # Scraped 2026-07-08 from /heroes/meta/trends (sorted by ratingScore).
    # Wraith King ranked #1, Spectre #2; Wilson on (winCount, matchCount)
    # must reproduce that order. Numbers are rounded on the page, so only the
    # ORDER is asserted, not exact scores.
    wraith_king = wilson_lower_bound(490326, 882600)   # ~55.6%, 882.6k
    spectre = wilson_lower_bound(357530, 647700)        # ~55.2%, 647.7k
    assert wraith_king > spectre
