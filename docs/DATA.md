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

The model-facing `TeamRef` and professional-player `PlayerRef` are opaque,
runtime-scoped references backed by the provider identity index. They are
passed as nested objects between independent tools and do not contain provider
IDs. Artifact construction has a separate Steam-native player reference for
recorded game data; the two `PlayerRef` contracts must not be conflated.

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
identifiers internally. Provider-private identifiers are data-layer
implementation details, not an agent language and not part of a model-facing
canonical artifact. Dota/Valve-native identifiers may cross the artifact
boundary when they identify a canonical Dota domain object, such as a Valve
match or team, a Steam account, or a hero, item, or ability.

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
provider JSON, provider schemas, and provider-private resource IDs remain
below the artifact boundary. Canonical Dota/Valve-native IDs may remain in an
artifact when they express domain identity. Artifact sections are data views,
not reasons to create a specialized tool for every user question.

## GameSummaryArtifact schema version 3

### Purpose

`GameSummaryArtifact` schema version 3 defines provider-neutral, canonical Dota
facts for one game. It is neither a provider DTO, a database record, nor a full
replay representation. It is intended to support:

- post-game scoreboard or dashboard views
- player performance grounded in recorded game facts
- item and build lookup
- skill-build lookup
- draft inspection
- future bounded artifact retrieval

The artifact is a canonical, normalized view of one game, not a precomputed
answer to a particular question.

### Structure

The schema version 3 canonical structure is:

```text
GameSummaryArtifact
├── artifact_type = "game_summary"
├── schema_version = "3"
├── game
│   ├── valve_match_id
│   ├── start_time
│   ├── duration_seconds
│   ├── winner
│   ├── game_mode
│   │   ├── id
│   │   └── name
│   └── lobby_type
│       ├── id
│       └── name
├── teams
│   ├── radiant
│   │   ├── valve_team_id
│   │   ├── name
│   │   └── score
│   └── dire
│       ├── valve_team_id
│       ├── name
│       └── score
├── players[]
│   ├── identity
│   │   ├── steam_account_id
│   │   ├── registered_name
│   │   └── persona_name
│   ├── side
│   ├── player_slot
│   ├── hero
│   │   ├── id
│   │   └── name
│   ├── stats
│   │   ├── level
│   │   ├── kills
│   │   ├── deaths
│   │   ├── assists
│   │   ├── last_hits
│   │   └── denies
│   ├── economy
│   │   ├── net_worth
│   │   ├── gold_per_min
│   │   └── xp_per_min
│   ├── items
│   │   ├── inventory[]
│   │   │   ├── slot
│   │   │   ├── id
│   │   │   └── name
│   │   ├── backpack[]
│   │   │   ├── slot
│   │   │   ├── id
│   │   │   └── name
│   │   └── neutral_items[]
│   │       ├── slot
│   │       ├── id
│   │       └── name
│   ├── purchase_history[]
│   │   ├── time_seconds
│   │   ├── item_id
│   │   └── item_name
│   └── ability_upgrades[]
│       ├── level
│       ├── time_seconds
│       ├── ability_id
│       └── ability_name
└── draft
    ├── picks[]
    │   ├── order
    │   ├── side
    │   ├── hero_id
    │   └── hero_name
    └── bans[]
        ├── order
        ├── side
        ├── hero_id
        └── hero_name
```

### Identifier boundary

Provider-private identifiers must remain below the artifact boundary. This
includes PandaScore match, game, team, and player resource IDs, as well as
other provider-private resource IDs. A PandaScore team ID is not a Valve team
ID, and a PandaScore game ID is not a Valve match ID; numeric coincidence never
permits their namespaces to be mixed.

Dota/Valve-native identifiers are canonical domain identity and may appear in
this artifact: Valve match IDs, Valve team IDs, Steam account IDs, and hero,
item, and ability IDs. `valve_match_id` is therefore the canonical game
identity, rather than an ambiguous `match_id` or any provider resource ID.

### Entity resolution

Canonical artifact entity representations use Valve-native hero, item, and
ability IDs, Steam account IDs, and Valve team IDs. Provider-private IDs are
excluded. Catalog resolution preserves the native ID and uses `name = null`
when no catalog name is available.

### Source-backed normalization and exclusions

Every schema version 3 fact is source-backed. The artifact may contain provider
source facts, canonical semantic normalization, and static Dota catalog
normalization. For example, normalization may represent `radiant_win` as
`winner = radiant` or `dire`, map a source team-side code such as `0` or `1` to
`radiant` or `dire`, and map hero, item, ability, game-mode, or lobby-type IDs
to canonical catalog names.

Schema version 3 excludes DotaMind-derived analytics and estimates. It must not
add KDA, total gold derived from GPM, total XP derived from XPM, lane
efficiency, teamfight participation, benchmarks, rankings, or scores.
Normalization may make a source fact semantically canonical; it must not invent
an analytical fact.

### Player and catalog semantics

Player identity is the three-field object `steam_account_id`,
`registered_name`, and `persona_name`. There is no unified `player_name`
fallback. `side` and `player_slot` describe that player's placement in this
game, so they belong on each player entry rather than inside persistent
identity.

Hero, item, and ability names are catalog-normalized companions to their native
IDs. All ordinary and neutral items use the same canonical Item Catalog: Dota
item ID to catalog to `id` and canonical `name`. OpenDota neutral source slots
are normalized into `neutral_items` as positional `ItemSlot` entries. The
collection always has slots 0 and 1, and there is no separate enhancement
semantic.

Player stats and economy values are copied from provider-recorded match facts
when available. They are not derived by DotaMind. In particular, KDA, estimated
total gold, and estimated total XP are not calculated from these fields.

When OpenDota provides an ID-only `ability_upgrades_arr` sequence, artifact
construction preserves the ability IDs and source order; unavailable level and
timing metadata remain `null`.

### Purchase history canonicalization

OpenDota `purchase_log` provides purchase time and an item key. The provider
adapter preserves this as a construction-level `item_key`; it does not perform
catalog resolution. During artifact construction, `ItemResolver` resolves
`item_key` to Valve-native item identity and canonical display name.

If an `item_key` cannot be resolved to a Valve item identity, that purchase
event is omitted rather than creating an identity-less `PurchaseEvent` or
failing the entire artifact. `purchase_history` preserves source event order.

### Missing-data and fixed-structure semantics

The artifact uses one missing-data contract:

- A missing source scalar fact is `null`.
- A represented canonical entity requires its native identity; an object without
  that identity is omitted rather than represented as an empty entity.
- A missing catalog mapping preserves the native ID and uses `name = null`.
- A missing collection is `[]`.
- A fixed structure remains present even when its fields or nested values are
  unavailable.

The fixed objects are `game`, `teams`, each player's `stats`, `economy`, and
`items`, and `draft`.

For example, missing `purchase_history` and `ability_upgrades` are `[]`. Missing
draft data is `draft: { picks: [], bans: [] }`. Inventory and backpack slot
structure is preserved even for empty slots, for example
`{ slot: 2, id: null, name: null }`. Missing `neutral_items` is represented by
the two empty neutral slots described below.

Inventory, backpack, and neutral item placement is positional. `neutral_items`
is always a fixed two-slot positional collection: slot 0 corresponds to the
first neutral source slot and slot 1 corresponds to the second. An empty slot
remains represented with `id = null` and `name = null`.

```json
"neutral_items": [
  {
    "slot": 0,
    "id": null,
    "name": null
  },
  {
    "slot": 1,
    "id": 1700,
    "name": "Mystical"
  }
]
```

### Schema evolution

Version 3 replaces neutral item value entries with positional `ItemSlot`
entries so both neutral source positions remain observable when one is empty.
It also permits ID-only ability upgrades to retain source IDs and order with
`level` and `time_seconds` set to `null` when that metadata is unavailable.

Provenance, freshness, coverage, completeness, and known missing sections
remain part of the artifact quality contract.

> `GameSummaryArtifact` schema v3 and Commit 3.5 do not yet persist
> `fetched_at`, provenance, coverage, completeness, or known-missing metadata.
> These remain target artifact-quality contracts for a later explicit
> schema/storage contract.

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
