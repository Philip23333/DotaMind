# Architecture

## Status

This is the vNext target architecture. Code describes current behavior; this
document describes the intended long-term boundaries. `ARTIFACTS.md` owns the
Artifact externalization, corpus, and migration contract.

The current code still contains a heavier GameSummary construction pipeline with
construction-only Ref wrappers and catalog enrichment. That implementation is
transitional and is intentionally being simplified rather than extended.

## Principles

- The model owns ordinary business reasoning and decides which facts or tools it
  needs.
- Tools expand the model's observable fact space; they do not encode user
  scenarios as workflows.
- Prefer small orthogonal capabilities such as search, lookup, grep, and read.
- Deterministic code owns hard boundaries: validation, provider transport,
  canonical identity, cross-source resolution, authorization, persistence,
  limits, and errors.
- Keep model context bounded. Complete large results may live outside context and
  remain addressable through locators.
- Do not create abstractions merely to mirror every provider field or Dota
  entity.
- A Ref is a locator passed between capabilities, not a generic wrapper for any
  value that has an ID.

A useful review question is:

> Is application code increasing what the model can observe, or replacing the
> model's ability to understand and combine the observed facts?

## System boundary

```text
User
  -> Product Chat API
  -> Agent Runtime
  -> LLM <-> Dota Tools
               -> Domain / Resolution
               -> Artifact Corpus
               -> Catalog
               -> Provider Adapters
               -> External Sources
```

The API owns authentication, browser request ownership, and durable dialogue
persistence. Agent Runtime owns the native tool-calling loop, execution limits,
streaming, deadlines, cancellation, and model protocol. It does not own Dota
business workflows or Artifact lifecycle.

Provider adapters own transport, provider authentication, provider schemas,
rate-limit/retry policy, and conversion from raw responses into verified
source-level models.

Domain/Resolution owns esports navigation identity, deterministic provider
mapping, cross-source game resolution, ambiguity, and bounded domain results.

The Artifact Corpus owns complete canonical documents that should not enter
model context automatically. Catalog owns static Valve ID reference facts.

## Agent loop

The runtime is a thin native tool-calling loop:

```text
messages
  -> model response
  -> final answer OR tool calls
  -> validated tool execution
  -> tool-result messages
  -> model continuation
```

It enforces maximum steps/tool calls, request deadlines, cancellation, stable
errors, and text streaming. It does not use an ExecutionPlan DSL, scenario
router, evidence DSL, or fixed search/read sequence.

Current-run tool messages stay in one execution. Historical tool calls/results
are not restored across browser turns; durable conversation persistence contains
User and Final Assistant dialogue only.

## Model-facing capability style

A capability should expose one independent fact-space or access primitive.
Typical shapes are:

```text
search / lookup
  -> bounded candidates + locator

grep
  -> locator + structural path + preview

read
  -> bounded content at locator/path
```

The model decides which observations matter to the question.

Tool descriptions state capability, inputs, outputs, and material limits. They
do not prescribe a scenario-specific sequence.

## Esports navigation domain

The current canonical esports navigation domain is:

```text
League -> Series -> Tournament -> Match -> Game
```

PandaScore is the current primary source for this hierarchy and its readable
event context.

Domain refs are used only where cross-capability navigation needs a stable
locator. Provider-private IDs remain internal. One provider entity must have one
canonical Ref-construction rule; services do not define competing identity
recipes.

The model may receive small domain objects and refs from capabilities such as
Series, Match, Team, and Player search/detail.

## Cross-source Game resolution

The current game data chain is intentionally simple:

```text
PandaScore
  -> identify League / Series / Tournament / Match / Game
  -> resolve concrete PandaScore Game
  -> cross-source resolver
  -> canonical valve_match_id
  -> OpenDota game detail
```

PandaScore answers what esports event/game this is. OpenDota answers what
happened in the already-resolved Valve game.

The resolver is deterministic application/domain code, not a model-facing tool.
Unresolved or ambiguous mappings remain explicit rather than being guessed.

## Valve-native identity and Catalog

Valve match/team IDs, Steam account IDs, and hero/item/ability IDs are canonical
Dota-native facts. They may cross the Artifact boundary directly.

Static ID -> entity translation belongs to the committed local Valve catalog,
not to dynamic Artifact construction. The model should receive small catalog
capabilities such as:

```text
catalog.search(text, optional types)
  -> Valve-native candidate IDs

catalog.lookup(hero/item/ability ID batches)
  -> static names/localization/reference facts
```

This avoids copying static names into every dynamic game document and avoids a
construction Ref type for every Valve ID.

## Artifact boundary

Artifact exists because complete tool results may be too large for model
context.

The target path is:

```text
complete source-backed result
  -> light canonical normalization
  -> JSON-like Artifact document
  -> ArtifactStore
  -> ArtifactRef

bounded tool result + ArtifactRef
  -> model context
```

The Artifact is a document substrate, not a second Domain object graph.

For a GameSummary document, readable PandaScore event context may be composed
with OpenDota recorded game facts. Provider-private IDs remain below the
boundary. Valve-native hero/item/ability IDs remain ordinary scalar fields.

The current `GameConstructionContext` plus construction-only Ref/catalog-
enrichment pipeline is transitional. The target is a thin normalizer that
validates source semantics and produces the canonical document directly.

See `ARTIFACTS.md` for the detailed target and migration order.

## Artifact production

A normal capability may externalize a large complete result as part of its own
successful data path. For resolved match detail, production conceptually is:

```text
valve_match_id
  -> OpenDota fetch
  + already-known PandaScore event context
  -> thin canonical Game document
  -> ArtifactStore.put
  -> ArtifactRef
```

The model does not need a separate `artifact.produce` capability for ordinary
match-detail flow.

Production is not an Agent Runtime stage. The runtime only dispatches the
capability that happens to reach this data boundary.

Artifact persistence may use Redis retention; retention is not freshness and a
missing/expired Artifact does not invalidate canonical Game identity.

## Artifact corpus exploration

Artifacts form a structured corpus outside context.

`artifact.search` remains exact availability lookup where useful.

`artifact.grep` is the generic breadth primitive:

```text
serialized Artifact corpus
  -> literal/schema-neutral scalar search
  -> ArtifactRef + structural path + bounded preview
```

`artifact.read` is the generic depth primitive:

```text
ArtifactRef + structural path
  -> bounded serialized value
```

Search/read never fetch providers or produce missing Artifacts. They do not
understand Hero, Player, Match, build, inventory, or another scenario-specific
business dimension.

A future generic index may replace scanning for performance without changing the
public contract.

## Artifact scope

Scope remains a generic membership relation:

```text
ArtifactScopeRef -> ArtifactRef[]
```

Known navigation ancestry may register a successful Game Artifact under League,
Series, Tournament, and Match locators. `ArtifactScopeStore` itself does not know
what those locators mean.

Membership is not inferred from Artifact content. Scoped search describes only
currently materialized corpus coverage.

Because scopes reuse navigation identity, inconsistent navigation Ref creation
is a data-integrity defect and must fail closed rather than silently broaden a
search.

## Context boundary

The model does not receive these by default:

- raw provider payloads
- a complete large match/game dump
- an entire Artifact
- static catalog duplication for every Valve-native ID

Normal model-facing results contain bounded data such as:

- navigation candidates and refs
- canonical Valve identity
- concise status/coverage/error information
- ArtifactRef
- bounded grep/read results
- catalog lookup results requested by the model

The model decides whether additional detail is useful.

## Sessions and persistence

The product chat API owns browser session authorization and PostgreSQL dialogue
persistence. `ConversationContextBuilder` projects the durable transcript into a
bounded recent model context; the durable transcript itself remains complete.

The runtime remains session-neutral and does not know browser session IDs or
PostgreSQL rows.

Artifacts are cross-run data outside the transcript. Failed-run traces are
separate debugging evidence. Neither Artifact content nor tool traces are
restored as historical dialogue by default.

Redis may retain Artifacts and failed-run traces under separate retention
contracts. Durable AgentRun/reconnect/replay infrastructure is added only after a
demonstrated product need.

## Reliability and provenance

Provider/domain capabilities preserve explicit source, freshness where useful,
ambiguity/resolution status, truncation, coverage, and warnings.

A cross-source inference is never presented as a native provider fact. A missing
Artifact is an availability state, not an identity rewrite. A catalog miss does
not change the Valve-native ID.

Do not add a large provenance/completeness framework to Artifact schema without a
concrete consumer; keep metadata source-backed and proportionate to observed
needs.

## Rejected designs

- ExecutionPlan or reference-path planning DSLs
- model-authored evidence obligations
- intent/scenario routers that select fixed workflows
- provider-level tools or provider-ID reasoning by the model
- one prompt/program per match, tournament, or player scenario
- one tool per Artifact section
- one Artifact search adapter/projector per schema
- a construction Ref type for every Hero, Item, Ability, slot, purchase, or
  event
- mandatory catalog enrichment inside dynamic Game Artifact production
- treating search -> read as a required sequence
- semantic/vector search before a demonstrated need
- a generic identity framework when a small canonical construction rule is
  sufficient
