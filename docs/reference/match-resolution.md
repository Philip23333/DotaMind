# PandaScore to Valve Match Resolution

## Purpose

PandaScore fixture data and OpenDota match data use separate identifiers. A
PandaScore game is mapped to a Valve match only when deterministic signals leave
one candidate. This is a data-layer reference, not an agent workflow.

## Verified matching signals

1. Normalize competition names and match a unique OpenDota league for the
   competition name and year.
2. Resolve both teams. If a team name has several candidates, use exact
   participation in the target OpenDota league as the only disambiguator.
3. Compare league matches using unordered team-ID equality, start-time delta no
   greater than 1800 seconds, duration delta no greater than five seconds, and
   winner consistency when a winner is available.
4. Return a Valve match ID only when exactly one record remains.

OpenDota series ID and game position are not hard constraints: the league-match
feed can omit or incompletely populate them.

## Outcomes

Possible outcomes include resolved, league_not_found, ambiguous_league,
team_not_found, ambiguous_team, insufficient_signals, not_found, and
ambiguous_match. A non-resolved outcome is a valid result; no closest-match or
weighted fallback is permitted.

## Provenance

A successful mapping is inferred_cross_source. It records candidate count,
matching signals, and time or duration deltas, and is never represented as a
native PandaScore Valve match ID.

## Maintenance

These rules came from verified Legacy V3 integration work. Revalidate them
against current provider responses before implementing vNext, especially
tolerances and fields that depend on changing provider data.
