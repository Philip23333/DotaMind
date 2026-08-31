# Project Direction

This branch is the DotaMind vNext clean-slate rewrite. The Legacy V3 baseline is
frozen at Git tag `pre-vnext-rewrite`.

Before architecture or product work, read:

1. `docs/PRODUCT.md`
2. `docs/ARCHITECTURE.md`
3. `docs/TOOLS.md`
4. `docs/DATA.md`
5. `docs/ARTIFACTS.md` when work touches large-result externalization,
   Artifact storage/search/read, or the current simplification migration
6. `docs/EVALS.md`
7. `docs/ROADMAP.md` when the work belongs to a planned phase

Code may intentionally lag the target documents during an active migration. Do
not preserve Legacy or transitional vNext structure merely because it exists.

# Architecture Rules

- The model owns ordinary Dota reasoning and decides which capabilities and
  observations to compose.
- Model-facing tools describe capabilities, not provider endpoints. Current
  provider implementations stay below the tool contract.
- Provider names are valid provenance in results. Provider implementation detail
  is not a reason to create one model-facing tool per provider.
- Different providers implementing the same capability are not required to fit
  one universal business DTO. Preserve complete validated, source-attributed
  business facts when their schemas genuinely differ.
- Do not add scenario-specific workflows, routers, prompt recipes, ExecutionPlan
  DSLs, or model-authored evidence obligations.
- Deterministic code protects provider transport, validation, canonical Valve
  identity, cross-source resolution, authorization, persistence, bounds, and
  stable errors.
- Raw provider-private IDs are not an agent language. Externalized entities are
  continued through ArtifactRef and generic Artifact access; new remote entities
  are discovered through semantic capabilities again.
- Canonical Valve-native IDs such as `valve_game_id`, `hero_id`, `item_id`, and
  `ability_id` may remain directly observable Dota facts. Provider adapters may
  keep the provider's native vocabulary internally; for example OpenDota may use
  `match_id` below the `game.detail(valve_game_id=...)` boundary.
- A Ref exists to locate something again; do not wrap every nested value or event
  structure in a Ref type.
- Prefer deletion over compatibility shims when replacing transitional vNext or
  Legacy behavior.

# DSH-Inspired Capability Implementation Pattern

DotaMind capability implementation intentionally follows the architectural idea
used by dsh: keep the model-facing consumer, the capability/service definition,
and the provider implementation independent from one another.

Use this conceptual seam:

```text
Model
  ↓
semantic Tool / Consumer
  ↓
Capability Service / Service Definition
  ↓
Provider implementation
  ↓
Provider Adapter / transport
```

The important property is dependency direction: the consumer depends on a DotaMind
capability contract, not on PandaScore/OpenDota endpoint vocabulary or provider
DTOs. The Provider decides how to satisfy that contract from its source. An
Adapter should remain focused on provider transport and source validation.

`esports.search` is the accepted reference implementation for this pattern:

```text
Model
  ↓
esports.search
  ↓
EsportsSearchService
  ↓
PandaScoreEsportsProvider
  ↓
PandaScoreAdapter
  ↓
complete validated source entity
  ↓
Source Artifact + bounded observation
```

When adding or replacing a capability, study `esports.search` before introducing
new architecture. Reuse the same ideas unless the new capability has a verified
reason to differ:

- expose one small semantic model-facing contract;
- keep provider names, endpoints, pagination, and private IDs below that contract;
- let the Service coordinate capability semantics, Artifact externalization, and
  stable result/error behavior;
- let the Provider/Adapter retain complete validated provider business facts;
- externalize large facts to an Artifact and return only a bounded observation;
- let the model choose what to inspect later with generic Artifact primitives;
- do not create scenario DTOs or manually curate fields merely because a current
  question only needs a subset of the source response.

Artifact fidelity and model context are separate concerns. The default data path
for a large provider result is:

```text
Provider response
  ├─→ complete validated source-backed Artifact
  └─→ bounded model-facing observation
```

Do not replace that with:

```text
Provider response
  → hand-picked fields for known scenarios
  → synthetic summary DTO
```

Validation, harmless normalization, and explicit capability enrichment are
allowed. They must not silently discard valid provider business facts merely
because DotaMind does not yet have a consumer for those fields.

`game.detail` must follow the same implementation philosophy. Its public input is
`valve_game_id`; OpenDota may continue to use its native `match_id` internally.
The intended path is conceptually:

```text
Model
  ↓
game.detail(valve_game_id)
  ↓
Game detail capability/service
  ↓
OpenDota implementation / adapter (`match_id` internally)
  ↓
complete validated OpenDota game response
  ↓
Game Artifact + bounded observation
```

Do not rebuild the historical GameSummary field-selection pipeline as the core of
`game.detail`. Historical GameSummary schemas may remain frozen for migration,
but the new detailed-game capability should preserve the provider's complete
validated game fact space and let Artifact access control what reaches model
context.

A second provider may justify a shared Provider protocol/router later. One
provider alone does not justify speculative provider-selection machinery; the
capability boundary itself is the required seam.

# Capability Rules

The target model-facing capability layer is intentionally small.

- `esports.search` is the broad esports discovery capability. PandaScore is its
  current implementation, not a separate model-facing namespace.
- `game.detail` is the detailed recorded-game capability. Its public identity is
  `valve_game_id`; OpenDota is its current implementation and may use `match_id`
  internally.
- Future providers join an existing capability when they provide the same broad
  observation need. Do not first design a universal League/Series/Match or game
  detail DTO for them.
- Capability results should expose a small stable semantic envelope. Large source
  facts live behind `artifact_ref`; the immediate `facts` value is a bounded
  observation rather than a second domain DTO.
- `kind` in `esports.search` is DotaMind capability vocabulary, not a provider-
  defined object type.
- Add provider-selection/routing machinery only after a second real provider
  demonstrates the need. One implementation does not justify a plugin system.

# Artifact Rules

Artifacts exist primarily to keep complete large results outside model context
while preserving generic search/read access.

- Treat an Artifact as a stored, validated, source-backed JSON-like document,
  not a universal Dota object graph.
- Preserve complete validated provider business facts by default. Do not decide
  field-by-field what is worth retaining based on known prompts or current
  product scenarios.
- Validation may normalize source values harmlessly, but it must not intentionally
  narrow a source document into a summary. Provider HTTP headers, credentials,
  request tokens, and transport/pagination envelopes are not business facts and
  need not be retained.
- Do not require different game-detail providers to normalize into one synthetic
  GameSummary schema merely so they can be stored.
- Keep the outer document/storage contract stable and provider provenance
  explicit; preserve source-shaped facts inside the document where useful.
- Keep static Valve catalog facts separate from dynamic recorded-game facts.
  Prefer small `catalog.search` / batch `catalog.lookup` capabilities instead of
  duplicating names/localization into every large result.
- `artifact.grep` and `artifact.read` remain generic document-observation
  primitives and must not learn provider or gameplay-scenario semantics.
- Historical GameSummary v3/v4/v5 contracts remain frozen; do not silently
  mutate them while migrating to the source-backed document model.

# Development Rules

- Verify the current branch/head and relevant tests before changing behavior.
- Network/provider SDK calls belong only in provider adapters or provider
  implementations below a capability boundary.
- Do not add fallback or mock behavior that hides missing integrations or
  provider errors.
- Run focused tests for every behavior change and report only checks that really
  ran.
- Update core documents only when their long-term contract changes. Git history
  and tags hold implementation history; do not keep progress archives in docs.
- Keep `docs/reference/` for provider/cross-source facts expensive to rediscover;
  revalidate volatile facts before relying on them.

# Agent Development Guidelines

## Required design flow

- Follow: architecture confirmation -> one design unit -> implementation ->
  acceptance.
- State scope, non-goals, and layer boundaries before code changes.
- Prefer the smallest design that satisfies a verified need.
- Do not add abstractions, extension points, or workflows for hypothetical
  future providers.
- Record material decisions as `Decision`, `Reason`, and `Not included` when
  useful for preserving a boundary.

## Identity and continuation

- Distinguish canonical Dota identity from provider-private identity.
- Valve-native IDs can be canonical cross-source facts. In the model-facing Game
  vocabulary use `valve_game_id`; provider-specific code may retain its native
  naming below the capability boundary.
- Provider-private IDs may remain inside complete source Artifacts as evidence,
  but they are not supported model-facing tool inputs.
- `ArtifactRef` is the continuation handle for an entity/fact space already
  externalized by a capability. Use `artifact.read` / `artifact.grep` to explore
  it.
- If the model needs a new remote esports entity, use another semantic
  `esports.search` call rather than exposing provider navigation IDs or a generic
  model-facing SourceLocator.
- Transitional/internal SourceLocator machinery may exist during migration, but
  it is not the target agent language and must not shape new capability APIs.
- Do not synthesize cross-source identity from names/year merely to avoid a
  nullable or unresolved canonical identity.

## Schemas and data

- Base source models on verified provider data and explicit source semantics.
- A capability-level common envelope may be small; do not force source payloads
  into a shared field-by-field business schema without a concrete consumer.
- Preserve complete validated business facts even when no current prompt consumes
  them; use bounded observations, not field deletion, to control model context.
- Preserve missing-data and ambiguity semantics rather than filling gaps with
  guesses.
- Static catalog lookup and dynamic recorded-game facts are separate fact
  spaces; combine them in the model unless a concrete product requirement
  justifies materialization.
- Do not add DotaMind-derived gameplay analytics to source-backed documents.

## Delivery and review

- One commit should represent one architecture decision or implementation
  boundary plus its focused tests.
- Follow the migration order in `docs/ROADMAP.md`; do not spend commits repairing
  old navigation or summary machinery when the target capability replaces it,
  unless a live correctness issue must be contained temporarily.
- Keep old tools during a migration only as long as focused evals still depend on
  them; remove them after the replacement capability is accepted.
- Before review, check capability/service/provider separation, source attribution,
  Valve identity, Artifact fidelity, model-visible bounds, provider failure
  semantics, and the focused tests protecting the change.

Small semantic capabilities, complete source-backed facts, generic Artifact
access, and deletion of unnecessary normalization machinery are preferred over
framework-building.
