# Architecture

## Status

This document defines the vNext target architecture. The default model-visible
surface has source-backed `esports.search` and `game.detail` capabilities.
Transitional Team, Player, and `matches.get_detail` code remains internally for
migration, but those tools are not registered in the default Agent runtime.

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
       <-> game.detail
             -> GameDetailService -> OpenDotaAdapter -> ArtifactStore
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

`query` is textual discovery over complete source business facts, rather than a
provider `search[name]` parameter. A native source filter is permitted only when
it preserves that broader result set. A Team name used by `teams` must resolve to
exactly one source Team; not-found and ambiguous resolution are
`invalid_arguments`, whereas no shared Match after successful resolution is
normal empty success.

There is no model-facing `within`, `SourceLocator`, provider selector, sort,
pagination, `recent`, `all`, or esports `game` kind. Source-locator infrastructure
may remain internally for transitional capabilities, but `esports.search` does
not depend on or expose it.

The public result has a thin per-record envelope and explicit search-level
delivery state:

```text
records[]
  source
  kind
  artifact_ref
  facts
truncated
partial
warnings[]
  code
  source
  kind
```

Every successful record has an `ArtifactRef`. `facts` is a generic bounded
observation of the same complete source document; it is not a hand-authored
preview DTO. The model uses `artifact.read` or `artifact.grep` when it needs
deeper facts.

## PandaScore implementation

PandaScore is the current `EsportsSearchProvider`. Its allowed endpoint surface
is defined by [the endpoint guide](reference/pandascore-endpoints.md), not by
whatever endpoint happens to work in a development account.

For lifecycle discovery, a dedicated PandaScore lifecycle endpoint is
authoritative. The Provider does not apply a second entity status filter to its
rows; it applies local lifecycle filtering only to Team-to-Matches. It maps source
time fields into the capability order:

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
An OpenDota transport, configuration, or schema failure degrades the enrichment:
the Match remains available and each game has `valve_game_id=null` with
`resolution="unavailable"`. The Provider must not call PandaScore Game detail
endpoints.

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
stored document. Failed final writes do not create invalid records. If at least
one document is stored, the result is successful with `partial=true` and one
sanitized `artifact_externalization_failed` warning per failed entity. Only a
complete final-write failure returns `artifact_error`; successful writes are not
rolled back.

`artifact.read` and `artifact.grep` are provider-blind stored-document
operations. They never fetch PandaScore.

## Recorded-game detail

`game.detail(valve_game_id)` is an exact single-object capability. It fetches a
complete validated OpenDota-shaped document and writes:

```text
GameDetailArtifact
  artifact_type = game_detail
  schema_version = 1
  source = opendota
  valve_game_id
  facts
```

The canonical ArtifactRef is `game_detail:1:<valve_game_id>`. The immediate
result contains a generic bounded observation plus that ArtifactRef; complete
facts are explored with `artifact.read` or `artifact.grep`.

This path does not invoke GameSummary construction, catalog enrichment, or a
provider router. An OpenDota fetch/validation failure is `provider_error`; an
Artifact write failure is `artifact_error`, and neither returns a partial detail.

## Errors

Expected `esports.search` failures are model-visible and sanitized:

| Code | Meaning |
| --- | --- |
| `invalid_arguments` | A request violates a cross-field capability rule. |
| `provider_error` | A source discovery, validation, or other non-degradable Provider failure could not satisfy a valid request. |
| `artifact_error` | No final source document could be stored. |

Details may identify source, kind, argument, or capability. They must never
include credentials, authorization headers, or a traceback. Unexpected defects
continue to use the generic runtime error contract.

## Transitional boundaries

The legacy `PandaScoreLocatorIndex`, Ref-oriented MatchService, TeamService, and
PlayerService remain only where historical tests or migration code consume them.
They are not registered in the default Agent runtime and must not be expanded for
compatibility.

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
- provider-native filtering that can exclude a capability-level query match.
- turning an unavailable enrichment dependency into a false `not_found`.
- invalid ArtifactRefs or rollback after a partial Artifact externalization failure.
