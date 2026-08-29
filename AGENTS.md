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
  one universal business DTO. Preserve validated, bounded, source-attributed
  facts when their schemas genuinely differ.
- Do not add scenario-specific workflows, routers, prompt recipes, ExecutionPlan
  DSLs, or model-authored evidence obligations.
- Deterministic code protects provider transport, validation, opaque source
  locators, canonical Valve identity, cross-source resolution, authorization,
  persistence, bounds, and stable errors.
- Raw provider-private IDs are not an agent language. When a provider object must
  be referenced across calls, expose an opaque provider-scoped locator instead.
- Canonical Valve-native IDs such as `valve_match_id`, `hero_id`, `item_id`, and
  `ability_id` may remain directly observable Dota facts.
- A Ref/locator exists to locate something again; do not wrap every nested value
  or event structure in a Ref type.
- Prefer deletion over compatibility shims when replacing transitional vNext or
  Legacy behavior.

# Capability Rules

The target model-facing capability layer is intentionally small.

- `esports.search` is the broad esports discovery capability. PandaScore is its
  current implementation, not a separate model-facing namespace.
- `game.detail` is the detailed recorded-game capability. OpenDota is its
  current detail implementation after any required source-to-Valve resolution.
- Future providers join an existing capability when they provide the same broad
  observation need. Do not first design a universal League/Series/Match or game
  detail DTO for them.
- Capability results use a thin common envelope where needed for composition:
  source attribution, source-defined kind, opaque `SourceLocator`, and bounded
  source-backed facts. The facts payload may remain source-shaped.
- Add a provider-selection/routing framework only after a second real provider
  demonstrates the need. One implementation does not justify a plugin system.

# Artifact Rules

Artifacts exist primarily to keep complete large results outside model context
while preserving generic search/read access.

- Treat an Artifact as a stored, validated, source-backed JSON-like document,
  not a universal Dota object graph.
- Do not require different game-detail providers to normalize into one synthetic
  GameSummary schema merely so they can be stored.
- Keep the outer document/storage contract stable and the provider source
  explicit; preserve source-shaped facts inside the document where useful.
- Keep static Valve catalog facts separate from dynamic recorded-game facts.
  Prefer small `catalog.search` / batch `catalog.lookup` capabilities instead of
  duplicating names/localization into every large result.
- `artifact.grep` and `artifact.read` remain generic document-observation
  primitives and must not learn provider or gameplay-scenario semantics.
- Artifact scope, when used, is an opaque membership mechanism. It must not
  require a universal esports ontology.
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

## Identity and locators

- Distinguish canonical Dota identity from provider-scoped location.
- Valve-native IDs can be canonical cross-source facts.
- A PandaScore/other-provider object that only needs to be revisited should use
  an opaque `SourceLocator`; it does not need to become a DotaMind canonical
  `LeagueRef`, `SeriesRef`, `TournamentRef`, or `MatchRef`.
- A `SourceLocator` must preserve source and source-defined object kind while
  keeping the raw provider-private ID opaque.
- Do not synthesize cross-source identity from names/year merely to avoid a
  nullable or unavailable locator.

## Schemas and data

- Base source models on verified provider data and explicit source semantics.
- A capability-level common envelope may be small; do not force source payloads
  into a shared field-by-field business schema without a concrete consumer.
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
  the old canonical navigation-Ref hierarchy when the target capability replaces
  it, unless a live correctness issue must be contained temporarily.
- Keep old tools during a migration only as long as focused evals still depend on
  them; remove them after the replacement capability is accepted.
- Before review, check capability/provider separation, source attribution,
  locator opacity, Valve identity, model-visible bounds, provider failure
  semantics, and the focused tests protecting the change.

Small capabilities, source-backed facts, generic document access, and deletion
of unnecessary normalization machinery are preferred over framework-building.
