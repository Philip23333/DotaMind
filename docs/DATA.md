# Data

## Domain model

vNext centers on these provider-neutral objects:

- Competition
- Series or Match
- Game
- Team
- Professional Player
- Hero, Item, and Ability
- PlayerGamePerformance
- PlayerBuild

Tool results use these domain objects rather than direct PandaScore, OpenDota,
Valve, or future-provider response shapes.

## Identity

Each domain object has a canonical DotaMind reference and may carry provider
identifiers internally. Provider IDs are data-layer implementation details, not
an agent language.

Identity resolution must be deterministic and explainable. A unique mapping may
be returned as resolved; zero or multiple credible candidates remain not found
or ambiguous. The data layer must not choose a nearest candidate merely to keep
a conversation moving.

## Cross-source resolution

Competition, team, series, game, and player identities can differ across
providers. Domain services own:

- Query normalization and candidate generation
- Canonical reference creation
- Provider-ID mapping
- Cross-source match resolution
- De-duplication and conflict handling
- Explicit resolution status and provenance

The detailed, verified PandaScore-to-Valve matching rules live in
reference/match-resolution.md. They are reference material for an implementation,
not a requirement to retain Legacy code structure.

## Normalization and provenance

Providers are normalized into stable domain DTOs. Each returned fact retains:

- Source or sources
- Fetched time when available
- Identity or mapping status
- Warnings, coverage limits, and known missing fields

If a fact is inferred by combining providers, the result states that inference.
It never claims that an upstream provider directly supplied the derived field.

## Provider roles

Initial provider roles are selected for product value:

- PandaScore supplies esports competition and fixture discovery.
- OpenDota can supply Valve-match detail and recorded player game data after a
  valid match mapping exists.
- Valve Catalog supplies static hero, ability, and item facts from a committed
  official snapshot.

STRATZ is not part of the initial vNext provider commitment. It may be assessed
later for a concrete professional-player capability and must not reintroduce
ranked-meta analytics as an accidental product scope.

## Freshness and quality

Schedules, results, rosters, and parse coverage are volatile. Static catalog
data has an explicit snapshot version. The data layer returns incomplete,
ambiguous, delayed, or unavailable data as such; presentation must preserve
these limits rather than upgrading them to certainty.
