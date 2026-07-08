"""Wilson score lower bound — a confidence-aware win-rate rating.

STRATZ documents the `/heroes/meta/trends` "Rating" column (URL sort key
`ratingScore`) as a Wilson score computed from match win rate and total
match count ("利用比赛胜率和总比赛数量进行评级的威尔逊分数"). That field is
NOT exposed by the STRATZ GraphQL API (live-verified 2026-07-08: selecting
`ratingScore` on `HeroWinDayType` returns `Cannot query field 'ratingScore'`),
but the method is documented and fully determined by two raw fields DotaMind
already collects via `heroStats.winDay` — `winCount` and `matchCount` — so the
rating can be reproduced locally instead of invented.

The Wilson score LOWER BOUND is the standard ranking choice (Reddit "best"
comments, Evan Miller's formulation): a conservative lower estimate of the
true win rate that penalises small samples. A 60% win rate over 10 games
scores well below a 55% win rate over 100k games, which raw win-rate ranking
gets wrong. This is also the principled, continuous form of the discrete
`min_sample_size` thresholds in `config/policy.yaml` sample_policy.

Two caveats anyone consuming this must know:
- STRATZ does NOT publish the z (confidence level) behind their rating. The
  default 95% CI (z=1.96) is an assumption; state it in provenance. At the
  trends page's sample scale (n >= ~200k) z is immaterial to ordering
  (empirically the ranking is identical for z in [0.5, 2.58]); z only matters
  for small-sample tools, which DotaMind controls and labels itself.
- Inputs are raw integer counts, never a pre-rounded win rate, so no precision
  is lost and small samples stay honest.

See memory `stratz-trends-ratingscore-frontend-only` for the full
investigation and the empirical reproduction of STRATZ's displayed order.
"""

import math

DEFAULT_Z: float = 1.96
"""Assumed z = 95% two-sided normal quantile.

STRATZ does not publish the z used by their rating; this default must appear
in any provenance so the assumption is explicit, not hidden.
"""


def wilson_lower_bound(wins: int, n: int, z: float = DEFAULT_Z) -> float:
    """Lower bound of the Wilson score interval for a binomial proportion.

    Args:
        wins: observed wins (0 <= wins <= n). Raw count, not a rounded rate.
        n: total matches (n >= 0).
        z: normal quantile for the confidence level; default 1.96 (95% CI).

    Returns:
        Lower-bound rating in [0, 1], always <= wins/n. For n == 0 returns
        0.0 (no data -> ranks lowest; callers can detect no-data via the raw
        match count).

    Raises:
        ValueError: if wins/n/z violate 0 <= wins <= n, n >= 0, or z >= 0
            (fail loud; do not silently produce a number from bad input).
    """
    if n < 0 or wins < 0 or wins > n:
        raise ValueError(
            f"invalid counts: wins={wins}, n={n} (require 0 <= wins <= n, n >= 0)"
        )
    if z < 0:
        raise ValueError(f"invalid z={z} (require z >= 0)")
    if n == 0:
        return 0.0
    p = wins / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = p + z2 / (2.0 * n)
    spread = z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))
    return (center - spread) / denom
