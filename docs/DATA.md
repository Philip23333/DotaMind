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

A domain object is primarily an identity and meaning contract. It answers:

    What entity is this?

Examples include `CompetitionRef`, `MatchRef`, `GameRef`, `TeamRef`, and
`PlayerRef`. A valid reference identifies an entity even when no detailed
artifact is currently available.

## Domain Entity and Artifact

| | Domain entity or DTO | Canonical artifact |
| --- | --- | --- |
| Primary question | What is this? | What data has been collected about this? |
| Purpose | Communication between domain services and tools | Reusable storage and bounded retrieval |
| Typical size | Small and bounded | Potentially large, sectioned, and quality-tagged |
| Intended lifetime | Request or operation scope | Reusable cache or store scope; backend is a separate decision |
| Model context | Usually suitable as a bounded tool view | Not entered by default; exposed through summaries, refs, and bounded sections |
| Contents | Identity, normalized facts, resolution state | Canonical facts, sections, provenance, coverage, completeness, and missing data |

The distinction is intentional. A domain entity identifies and describes an
entity; an artifact records what normalized data has been collected about that
entity. A tool can return a domain reference and an artifact reference without
returning the complete artifact content.

## Identity

Each domain object has a canonical DotaMind reference and may carry provider
identifiers internally. Provider-specific identifiers are data-layer
implementation details, not an agent language and not part of a model-facing
canonical artifact.

Identity resolution must be deterministic and explainable. A unique mapping may
be returned as resolved; zero or multiple credible candidates remain not found
or ambiguous. The data layer must not choose a nearest candidate merely to keep
a conversation moving.

Identity and availability are independent. Resolving a `GameRef` does not imply
that scoreboard, draft, inventory, or timeline data exists. Availability is
reported through coverage and completeness metadata rather than by changing
the identity result.

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
reference/match-resolution.md. They are reference material for an
implementation, not a requirement to retain Legacy code structure.

## Canonical Artifacts

A canonical artifact is a DotaMind data object that a future artifact layer
could create from provider data after normalization. It answers:

    What normalized data has been collected about this entity?

Artifact fields use canonical entity references and normalized values. Raw
provider JSON, provider schemas, and provider-specific IDs remain below the
artifact boundary. Artifact sections are data views, not reasons to create a
specialized tool for every user question.

## GameSummaryArtifact v0

### Purpose

`GameSummaryArtifact v0` is the first proposed game-level artifact contract.
It is intended to support:

- post-game summary
- player overview grounded in recorded game facts
- player build lookup

The first validation example is:

    “Malr1ne 第二把出了什么装备？”

The artifact is a canonical, normalized view of one game. It is not a raw
provider response and is not a precomputed answer to a particular question.

### Structure

The proposed v0 structure is:

```text
GameSummaryArtifact
  game
    match_id
    duration
    winner
    teams

  players[]
    player_name
    account_id
    team
    hero

    stats
      kills
      deaths
      assists
      last_hits
      denies

    economy
      gold
      gold_spent
      gold_per_min
      xp_per_min

    items
      inventory
      backpack
      neutral

    purchase_history
    abilities

  draft
    picks
    bans
```

`game.match_id` is a canonical match reference or normalized match
identifier, not a provider-specific ID. Team, player, hero, item, and ability
values use canonical references or normalized names. `account_id`, when
available, means the normalized public player account identifier supplied by
provider data; it is not an adapter-specific provider record or payload field.

All fields in this artifact must originate in provider data. Normalization may
convert names, units, timestamps, and identities into canonical values, but it
must not silently invent facts. Provenance, freshness, coverage,
completeness, and known missing sections remain part of the artifact quality
contract.

The v0 artifact explicitly excludes derived analytics such as damage
percentage, participation rate, rating, custom score, or other computed
performance judgments. Such fields can be added only by a future, explicit
contract change; they are not implied by the v0 schema.

## Artifact lifecycle

The target data lifecycle is:

    Provider Fetch
      -> Normalization
      -> Artifact Store
      -> Retrieval
      -> bounded Tool View

This is a data lifecycle, not a mandatory A-to-B-to-C model workflow. An
existing artifact may be reused, a request may be answered by a bounded domain
result, and a missing artifact may produce an explicit unavailable result. The
artifact lifecycle does not belong to Agent Runtime: runtime transports
messages and dispatches tools, while domain and retrieval layers own data
quality and access semantics.

## Artifact quality

Every artifact or bounded artifact view should preserve the following metadata
when applicable:

| Field | Meaning |
| --- | --- |
| `source` | Provider or normalized source set that supplied the facts |
| `fetched_at` | Time the source data was obtained |
| `schema_version` | Version of the canonical artifact schema |
| `coverage` | Sections or fact families currently available |
| `completeness` | Whether the artifact is complete, partial, or otherwise limited |
| `missing` | Known sections or facts that are unavailable |

For example, a `GameArtifact` may report coverage for scoreboard, draft,
inventory, and purchase events while listing replay timeline under `missing`.
The absence must remain visible; a summary must not imply that unlisted data
was fetched or verified.

## Normalization and provenance

The proposed normalization path would produce stable domain DTOs and canonical
artifacts. Each returned fact should retain:

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
