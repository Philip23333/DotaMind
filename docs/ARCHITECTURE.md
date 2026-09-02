# Architecture

## Status

This document defines the vNext target architecture. The default model-visible
surface is `esports.search`, `game.detail`, `artifact.grep`, and `artifact.read`.

`esports.search` is a PandaScore-backed semantic discovery capability. Its
compact query grammar is validated against the generated PandaScore capability
document before one native collection request runs. Transitional Team, Player,
Series, and `matches.get_detail` code remains internally for migration, but
those tools are not registered in the default Agent runtime.

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
             -> PandaScoreNativeQueryExecutor -> PandaScoreAdapter
       <-> artifact.grep / artifact.read
             -> session Artifact store
       <-> game.detail
             -> GameDetailService -> OpenDotaAdapter
```

`esports.search` keeps provider endpoints and endpoint-local fields below the
tool boundary. A small source-shaped collection page remains inline. For a
large page, it stores the complete logical response in the current session and
returns a bounded structural preview plus a fresh opaque string ref; it does not
expose provider endpoints or paths.

## Capability pattern

Every capability follows one conceptual seam with dependency pointing from the
model down to the provider, never sideways into provider vocabulary:

```text
Model
  -> semantic Tool / capability contract
  -> Capability Service
  -> Provider implementation
  -> Provider Adapter / transport
  -> complete validated source document
       -> complete logical tool response + bounded observation when oversized
```

`game.detail` is the current reference implementation of this pattern:

```text
Model
  -> game.detail(valve_game_id)
  -> GameDetailService
  -> OpenDota implementation / adapter (match_id internally)
  -> complete validated OpenDota game response
  -> complete logical game.detail response + bounded observation when oversized
```

The Tool owns session Artifact externalization, bounded observations, and result
assembly. A Service owns capability validation and source retrieval. A Provider owns source endpoint selection,
source filtering, pagination, ordering, and source-specific enrichment. An
Adapter owns only provider HTTP transport and provider schema parsing.

The esports discovery seam uses one small semantic model-facing contract;
provider names, endpoints, pagination transport syntax, and private IDs remain
below that contract. It does not encode scenario-specific workflows or a
universal search DTO. Its observation policy preserves complete source-shaped
rows in one temporary response document when the serialized response is large, while keeping
discovery scalars and structural pointers in the immediate bounded result.

## PandaScore provider surface (preserved)

The PandaScore HTTP client remains at `app/vnext/providers/pandascore/`
(Adapter plus provider models). Its allowed endpoint surface is defined by
[the endpoint guide](reference/pandascore-endpoints.md), not by whatever
endpoint happens to work in a development account.

The following PandaScore discovery facts are preserved source knowledge for the
future seam:

- dedicated lifecycle endpoints are authoritative for their lifecycle; a
  second entity-status filter must not be applied to their rows;
- source time fields map to discovery order (`past`: actual end, otherwise
  actual start, otherwise planned start, descending; `upcoming`: planned start,
  ascending; `running`: actual start, descending); `modified_at` is provider
  metadata, never an event-recency signal;
- exact Team identity derives from the complete PandaScore Team corpus, with a
  TTL-bounded identity index for repeated constraints; exact normalized name,
  acronym, or slug matching never chooses arbitrarily among multiple exact
  candidates; the Team-to-Matches endpoint applies AND semantics locally;
- `truncated=true` marks that qualifying results may remain outside a provider
  scan or a final limit;
- PandaScore Game detail endpoints remain outside the allowlist.

## Match Game -> Valve ID enrichment

`ValveMatchIdResolver` remains available in the domain layer
(`app/vnext/domain/matches/`) and resolves selected Matches as one batch:
global OpenDota evidence is shared once per invocation and league-match evidence
once per unique league. Each source game gets:

```text
valve_game_id  canonical OpenDota/Valve match ID when resolved, otherwise null
resolution     the complete deterministic resolution status
```

An unresolved game is normal source uncertainty and does not discard its Match.
An OpenDota transport, configuration, or schema failure degrades the enrichment
to `resolution="unavailable"` rather than a false `not_found`.

## Artifact boundary

Artifacts are temporary session-owned JSON-like tool responses. Each oversized
response receives a fresh opaque `artifact:tool:<uuid4-hex>` ref; it has no
stable source identity and is never shared with another session. `artifact.read`
and `artifact.grep` require that exact ref (or a documented static manual) and
never fetch PandaScore or OpenDota. There is no Artifact corpus, type, schema,
scope, or model-facing `artifact.search` operation.

## Recorded-game detail

`game.detail(valve_game_id)` is an exact single-object capability. It fetches a
complete validated OpenDota-shaped document. Small logical responses remain
inline; large ones receive a fresh session ref and return a generic bounded
observation. Complete facts are then explored with `artifact.read` or
`artifact.grep` using that exact ref.

This path does not invoke GameSummary construction, catalog enrichment, or a
provider router. An OpenDota fetch/validation failure is `provider_error`; an
Artifact write failure is `artifact_error`, and neither returns a partial detail.

## Errors

Expected capability failures are model-visible and sanitized. For
`game.detail`:

| Code | Meaning |
| --- | --- |
| `provider_error` | OpenDota could not fetch, validate, or confirm the requested Valve game ID. |
| `artifact_error` | The complete detail document could not be stored. |

Details may identify source, argument, or capability. They must never include
credentials, authorization headers, or a traceback. Unexpected defects continue
to use the generic runtime error contract.

## Transitional boundaries

The legacy `PandaScoreLocatorIndex`, Ref-oriented MatchService, TeamService,
SeriesService, and PlayerService remain only where historical tests or
migration code consume them. They are not registered in the default Agent
runtime and must not be expanded for compatibility.

The target detailed-game path consumes the canonical `valve_game_id`. It does
not reintroduce PandaScore Game discovery as a model tool.

## Rejected designs

- provider-named model tool namespaces;
- a model-facing League -> Series -> Match -> Game navigation workflow;
- a universal cross-provider esports DTO;
- a unified search-engine abstraction with kind/`time_scope`/`teams` plumbing
  rebuilt from the removed `esports.search` contract;
- provider-private IDs as capability inputs;
- a provider router/plugin framework before a second provider exists;
- PandaScore Game detail endpoints outside the allowlist;
- provider-native filtering that can exclude a capability-level query match;
- turning an unavailable enrichment dependency into a false `not_found`;
- typed/stable Artifact identities, corpus discovery, or persistence for a
  partial Artifact externalization failure.
