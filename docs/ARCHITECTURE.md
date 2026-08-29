# Architecture

## Status

This is the vNext target architecture. Code describes current behavior; this
document describes intended long-term boundaries.

The current code exposes source-backed `esports.search` and transitional
`matches.get_detail`, and it still contains the heavier GameSummary construction
pipeline. `matches.get_detail` will be replaced by `game.detail`; the target is
a smaller capability layer with source-backed implementations and generic
Artifact externalization.

## Principles

- The model owns ordinary business reasoning and decides which observations it
  needs.
- Model-facing tools represent broad capabilities, not provider endpoints and
  not one API operation per provider object type.
- A capability may have one or more provider implementations. Provider names are
  visible as provenance in results; provider plumbing is hidden below the tool.
- Different providers do not need to be normalized into one universal business
  DTO merely because they implement the same capability.
- Preserve validated, bounded, source-attributed facts when providers expose
  genuinely different structures.
- Prefer small orthogonal capabilities such as search, detail, lookup, grep, and
  read over a large ontology-shaped tool surface.
- Keep complete large results outside model context and make them addressable by
  generic locators.
- Deterministic code owns provider transport, validation, opaque source
  locators, canonical Valve identity, cross-source resolution, persistence,
  bounds, authorization, and stable errors.

A useful review question is:

> Is application code giving the model access to a fact space, or is it
> pre-interpreting and reshaping that fact space into a programmer-designed
> worldview?

## System boundary

```text
User
  -> Product Chat API
  -> Agent Runtime
  -> LLM
       <-> esports.search
             -> PandaScore implementation
             -> future esports-search implementations
       <-> game.detail
             -> OpenDota implementation
             -> future game-detail implementations
       <-> catalog.search / catalog.lookup
             -> local Valve catalog
       <-> artifact.search / artifact.grep / artifact.read
             -> ArtifactStore / ArtifactScopeStore
```

The API owns authentication, browser request ownership, and durable dialogue
persistence. Agent Runtime owns the native tool-calling loop, execution limits,
streaming, deadlines, cancellation, and model protocol. It does not own Dota
business workflows or Artifact lifecycle.

Provider implementations own upstream transport and verified source models.
Capability services decide which implementation(s) can satisfy the broad
observation request and return a bounded, source-attributed result.

## Capability boundary

The model-facing abstraction is the capability, not the source schema.

For example:

```text
esports.search
  -> PandaScore search implementation today
  -> another esports data source later

game.detail
  -> OpenDota detail implementation today
  -> another recorded-game source later
```

A future provider is added under an existing capability when it answers the same
broad question. It does not require a second tool namespace and does not require
DotaMind to invent one field-by-field canonical schema first.

The common result contract should be deliberately thin. A source-backed record
may conceptually expose:

```text
source
kind
locator
artifact_ref
facts
```

where:

- `source` is explicit provenance such as `pandascore` or `opendota`;
- `kind` is a source-defined object kind such as PandaScore `series` or `match`;
- `locator` is an opaque `SourceLocator` used to revisit the same source object;
- `artifact_ref` addresses the validated stored source document when the
  capability externalizes it;
- `facts` is a generic bounded observation derived from that same source
  document, not a hand-authored business preview DTO.

This envelope is for composition, provenance, and bounded observation. It is not
a universal esports entity model.

## SourceLocator

`SourceLocator` replaces the need to promote every provider object into a
DotaMind canonical Domain Ref.

Conceptually:

```text
SourceLocator
  source
  kind
  opaque value
```

The opaque value may be backed internally by a provider-private ID, but the raw
ID is not exposed as agent navigation language. The locator asserts only:

> this is the same object in this source

It does not assert cross-source canonical identity.

Canonical Valve-native identities are different. `valve_match_id`, Valve team
ID, Steam account ID, hero ID, item ID, and ability ID are shared Dota facts and
may remain directly model-visible.

## Esports search capability

`esports.search` is the target broad discovery tool for competition/event/match
navigation.

PandaScore currently supplies the hierarchy:

```text
League -> Series -> Tournament -> Match -> Game
```

That hierarchy is treated as PandaScore source vocabulary, not as a DotaMind
universal ontology that every future provider must implement.

The search capability may support a text query, bounded time scope, an optional
`within` source locator, and a result limit. PandaScore-specific search/list
operations remain internal implementation choices.

For each discovered PandaScore source object, the provider implementation keeps
the validated provider-shaped business document outside model context and
returns:

```text
SourceLocator
ArtifactRef
bounded structural facts
```

The bounded facts are produced by one generic observation policy. DotaMind does
not maintain separate `LeaguePreview`, `SeriesPreview`, `MatchPreview`, or
`GamePreview` schemas. The model uses `artifact.grep/read` when it needs facts
that are not present in the bounded observation.

The current `series.search`, `series.list_matches`, and `matches.search` tools
are migration-era surfaces and should converge into `esports.search` after
focused evals prove the replacement.

## Game detail capability

`game.detail` is the target detailed recorded-game capability.

Current flow:

```text
PandaScore source locator / discovered game
  -> internal PandaScore-to-Valve resolution when needed
  -> canonical valve_match_id
  -> OpenDota detail implementation
  -> bounded result + ArtifactRef for large complete data
```

`game.detail` may also accept a canonical Valve match ID directly when one is
already known.

If a second game-detail provider is added later, the capability may return
multiple source-attributed results or choose an implementation according to an
explicit policy. It should not first merge all providers into one synthetic
`UnifiedGameDetail` object.

Cross-source resolution remains deterministic application code. Ambiguous or
unresolved mappings stay explicit and are not guessed by the model or hidden by
fallbacks.

## Source-shaped facts, not raw transport

"Source-shaped" means retaining the provider's business fact structure without
forcing it through a DotaMind universal business DTO. It does not mean storing
the HTTP transport envelope.

Provider implementations still:

- validate known upstream schema/types and source-specific null/missing
  semantics;
- remove credentials, headers, pagination envelopes, and transport-only
  metadata;
- preserve additional provider business fields when they can be safely carried;
- omit provider-private identity values from bounded model-facing observations;
- expose explicit source and provider failure state.

A stored source-document Artifact may retain provider-private IDs as source-local
evidence. Those values are not supported capability identity or cross-source
identity; navigation continues to use `SourceLocator`.

Bounding is applied at the model-facing observation/read boundary rather than by
discarding provider facts solely because no current scenario uses them.

What is intentionally avoided is the next layer that renames every provider
concept into a universal DotaMind League/Series/Tournament/Match/Game schema
without a concrete cross-source consumer.

## Valve catalog

Static Dota identity translation belongs to the committed local Valve catalog.
The model should use small capabilities:

```text
catalog.search(text, optional types)
  -> Valve-native candidate IDs

catalog.lookup(hero/item/ability ID batches)
  -> static names/localization/reference facts
```

Dynamic game-detail providers may return `hero_id`, `item_id`, and `ability_id`
directly. Artifact production does not need to copy static catalog names into
every large result.

## Artifact boundary

Artifact exists because complete provider results may be too large for model
context.

The target is:

```text
capability provider implementation
  -> complete validated source-backed result
  -> minimal stable document envelope
  -> ArtifactStore
  -> ArtifactRef

bounded observation + ArtifactRef
  -> model context
```

Artifact is therefore an externalized document substrate, not a requirement to
construct a provider-neutral GameSummary object graph.

A source-backed Artifact may conceptually contain:

```text
source
kind
canonical_ids    # only when truly shared, e.g. valve_match_id
facts            # complete validated provider-shaped document
```

Do not merge PandaScore event facts and OpenDota game facts into one universal
schema merely to make them searchable. Their relationship can be retained by
source locators, canonical Valve identity, bounded capability results, and
Artifact scope/membership where useful.

Historical GameSummary schemas v3/v4/v5 remain frozen. Source-backed documents
use a separate Artifact contract rather than silently mutating those historical
schemas.

## Artifact exploration

Artifacts form a structured corpus outside model context.

- `artifact.search` performs exact availability lookup where useful.
- `artifact.grep` is schema-neutral breadth search over serialized scalar
  content.
- `artifact.read` is schema-neutral bounded depth retrieval by ArtifactRef and
  structural path.

An ArtifactRef may come directly from another capability such as
`esports.search`; it does not have to be rediscovered through
`artifact.search`.

Search/read do not fetch providers or produce missing Artifacts. They do not
know PandaScore, OpenDota, Hero, Player, build, or another gameplay scenario.

A future index may replace scanning for performance while keeping the same
schema-neutral contract.

## Artifact scope

Scope remains a generic membership relation:

```text
ArtifactScopeRef -> ArtifactRef[]
```

The target scope mechanism must not depend on a universal League/Series/
Tournament/Match identity hierarchy. A capability may register an Artifact
under already-known opaque source locators or other explicit collections while
keeping scope itself provider- and schema-blind.

The current scope registrations based on DotaMind navigation refs are
transitional. Do not invest in expanding that ref hierarchy before the
`SourceLocator` capability contract is proven.

## Team and player capabilities

Existing Team/Player tools may remain while the esports/game capability
migration is executed. The same rule applies if a second provider is added:
prefer a broad capability with source attribution over a new universal DTO or a
provider-named tool tree.

Do not widen this migration merely to make all existing tools symmetrical.

## Context and persistence

The model does not receive transport payloads, complete large detail results, or
entire Artifacts by default.

Normal model-facing responses contain bounded facts, source attribution,
locators, canonical Valve IDs when available, ArtifactRefs, and explicit
ambiguity/truncation/failure state.

The product chat API owns PostgreSQL dialogue persistence. Agent Runtime remains
session-neutral. Artifacts and failed-run traces stay outside historical model
conversation context and use separate retention contracts.

## Rejected designs

- one model-facing tool namespace per provider when a broad capability exists
- one tool per PandaScore League/Series/Tournament/Match operation
- forcing every provider into one canonical esports hierarchy
- forcing every game-detail provider into one `UnifiedGameDetail` DTO
- provider-private IDs as model-facing capability identity
- one construction Ref type per Hero, Item, Ability, slot, purchase, or event
- mandatory catalog enrichment inside dynamic game documents
- one Artifact search adapter/projector per provider or schema
- scenario-specific Artifact search helpers
- automatic provider fetch from `artifact.grep` or `artifact.read`
- a provider routing/plugin framework before a second real implementation
- ExecutionPlan, evidence DSL, or fixed scenario workflows
