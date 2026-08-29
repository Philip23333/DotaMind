# PandaScore endpoint observations

## Scope

This note records observed PandaScore Dota endpoint behavior for the configured
account on 2026-08-29. It is not a replacement for PandaScore's official API
contract; provider plan access and routes must be revalidated before treating an
observation as a durable integration guarantee.

## Observed behavior

- `/dota2/matches/past`, `/dota2/matches/running`, and
  `/dota2/matches/upcoming` were usable for bounded match discovery.
- `GET /matches/1638249` returned HTTP 200 and included the match's game
  fixtures.
- `GET /dota2/matches/1638249` returned a route-not-found response and must not
  be used for single-match reuse.
- `GET /dota2/matches/1638249/games` was tested during investigation and
  returned HTTP 403. The capability does not depend on that endpoint.

## Integration rule

Discovery results may already contain the validated `PandaScoreMatch` and its
games. Keep that runtime-scoped snapshot behind the opaque Match locator; only
a cold locator falls back to `GET /matches/{id}`. This avoids treating an
unverified endpoint as a normal navigation step while preserving sanitized
provider errors for genuine fallback failures.

## Raw response snapshots

Bounded raw responses for every endpoint used by the adapter are stored under
[`pandascore-snapshots/`](pandascore-snapshots/). Each dated capture has a
`manifest.json` with its request path, non-sensitive parameters, and capture
status. The snapshots exclude headers and credentials and are observations of
the configured account, not a stable API contract.
