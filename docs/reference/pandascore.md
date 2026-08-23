# PandaScore Dota 2 Reference

## Role

PandaScore is the initial source for esports competition discovery and fixture
data. Its suitability is determined by the vNext product surface, not by every
resource available to an account plan.

## Verified constraints

- Dota 2 resources use the PandaScore Dota 2 namespace and bearer-token
  authentication.
- Fixture-list responses can provide opponents, results, streams, games, status,
  format, and scheduled-time context.
- List ordering should be explicit; descending scheduled time avoids relying on
  an upstream default ordering.
- Availability of detail endpoints and fields is account-plan dependent.
- On the verified free plan, fixture game records did not expose a Valve match
  ID. The game match_id field represented the parent PandaScore match, not a
  Valve identifier.
- Live schedules, results, streams, and counts are volatile and must not be
  asserted as stable documentation values.

## Consequences

Do not infer a Valve match ID from a PandaScore game ID. Use deterministic
cross-source resolution when match detail requires OpenDota data. Do not add web
scraping, paid endpoints, or undocumented fallback paths as an implicit
replacement for unavailable plan features.

## Maintenance

Provider plans, fields, status values, and rate limits change. Revalidate these
facts with the configured account before using them as an implementation contract.
