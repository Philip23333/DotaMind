# Architecture

## Status

This document defines the vNext target architecture. The current branch has the
source-backed `esports.search` capability and still contains transitional Team,
Player, and `matches.get_detail` tools. Those remaining tools do not enlarge the
`esports.search` contract.

## Principles

- The model chooses which broad capability observations to combine; application
  code does not encode question-specific workflows.
- Model-facing tools describe capabilities, never PandaScore endpoints or one
  tool per provider object type.
- A source implementation preserves validated, source-shaped business facts. It
  is not required to fit a universal League/Series/Tournament/Match DTO.
- Deterministic code owns transport, schema validation, source filtering,
  canonical Valve identity resolution, Artifact persistence, bounds, and stable
  errors.
- Raw provider IDs remain source evidence inside a stored document, not a
  model-facing tool language.

## System boundary

```text
User
  -> Product Chat API
  -> Agent Runtime
  -> LLM
       <-> esports.search
             -> EsportsSearchService
                  -> PandaScoreEsportsProvider
                       -> PandaScoreAdapter
                       -> ValveMatchIdResolver -> OpenDotaAdapter
                  -> ArtifactStore
       <-> artifact.search / artifact.grep / artifact.read
             -> ArtifactStore
       <-> game.detail (target)
             -> canonical valve_game_id -> OpenDota detail
```

`esports.search` has three deliberately separate layers:

```text
Model
  -> esports.search tool
  -> EsportsSearchService
  -> EsportsSearchProvider
  -> PandaScoreEsportsProvider
  -> PandaScoreAdapter
```

The Service owns capability validation, exact source-identity de-duplication,
the final limit, Artifact externalization, bounded observations, and result
assembly. A provider owns source endpoint selection, source filtering,
pagination, ordering, and source-specific enrichment. The Adapter owns only
PandaScore HTTP transport and PandaScore schema parsing.

## Esports search contract

The complete model-facing request is:

```text
kind        required: league | series | tournament | match | team | player
query       optional text discovery
teams       optional Match-only team-name constraints; every name is required
time_scope  optional: upcoming | running | past
limit       1..50, default 10
```

`time_scope` is valid only for `series`, `tournament`, and `match`. `teams` is
valid only for `match`, with AND semantics. Empty results are a normal successful
observation. A query names exactly one source kind; it never fans out into mixed
League/Series/Match results.

There is no model-facing `within`, `SourceLocator`, provider selector, sort,
pagination, `recent`, `all`, or esports `game` kind. Source-locator infrastructure
may remain internally for transitional capabilities, but `esports.search` does
not depend on or expose it.

The public result envelope is intentionally thin:

```text
source
kind
artifact_ref
facts
```

Every successful record has an `ArtifactRef`. `facts` is a generic bounded
observation of the same complete source document; it is not a hand-authored
preview DTO. The model uses `artifact.read` or `artifact.grep` when it needs
deeper facts.

## PandaScore implementation

PandaScore is the current `EsportsSearchProvider`. Its allowed endpoint surface
is defined by [the endpoint guide](reference/pandascore-endpoints.md), not by
whatever endpoint happens to work in a development account.

For lifecycle discovery, the Provider maps PandaScore source fields into the
capability order:

- `past`: actual end, otherwise actual start, otherwise planned start;
  descending;
- `upcoming`: planned start; ascending;
- `running`: actual start; descending.

`modified_at` is provider metadata, never an event-recency signal. The Provider
may fetch several source pages and filter locally; it marks `truncated=true`
whenever qualifying results may remain outside its scan or the final limit.

For Match `teams`, the Provider searches each supplied Team source identity using
exact normalized name, acronym, or slug matching. It never chooses arbitrarily
among multiple exact candidates. It then queries the allowed Team-to-Matches
endpoint and applies AND filtering locally.

## Match Game -> Valve ID enrichment

PandaScore Match documents retain their complete `games[]` source facts. Before
the document leaves the Provider, it reuses `ValveMatchIdResolver.resolve_many()`
once per Match. Each source game gets:

```text
valve_game_id  canonical OpenDota/Valve match ID when resolved, otherwise null
resolution     the complete deterministic resolution status
```

An unresolved game is normal source uncertainty and does not discard its Match.
An OpenDota transport, configuration, or schema failure is a Provider failure,
not a fabricated `not_found` resolution. The Provider must not call PandaScore
Game detail endpoints.

## Artifact boundary

For final unique entities only, `EsportsSearchService` creates a stable source
document ArtifactRef from `(source, kind, source_identity)`, writes:

```text
source
kind
fetched_at
facts  # complete validated provider-shaped document
```

and returns a bounded observation derived from `facts`. A repeat search of the
same source identity uses the same ArtifactRef; the latest write replaces the
stored document. If any final Artifact write fails, the whole search returns
`artifact_error`; it does not expose partial records.

`artifact.read` and `artifact.grep` are provider-blind stored-document
operations. They never fetch PandaScore.

## Errors

Expected `esports.search` failures are model-visible and sanitized:

| Code | Meaning |
| --- | --- |
| `invalid_arguments` | A request violates a cross-field capability rule. |
| `provider_error` | A source adapter or required enrichment dependency could not satisfy a valid request. |
| `artifact_error` | A final source document could not be stored. |

Details may identify source, kind, argument, or capability. They must never
include credentials, authorization headers, or a traceback. Unexpected defects
continue to use the generic runtime error contract.

## Transitional boundaries

The legacy `PandaScoreLocatorIndex` and Ref-oriented MatchService remain only
where current transitional detail tools still consume them. They are not part of
the new `esports.search` path and must not be expanded for compatibility.

The target detailed-game path consumes the canonical `valve_game_id` retained in
a Match Artifact. It does not reintroduce PandaScore Game discovery as a model
tool.

## Rejected designs

- provider-named model tool namespaces;
- a model-facing League -> Series -> Match -> Game navigation workflow;
- a universal cross-provider esports DTO;
- provider-private IDs as capability inputs;
- a provider router/plugin framework before a second provider exists;
- PandaScore Game detail endpoints outside the allowlist;
- partial successful records after an Artifact externalization failure.
