# Project Direction

This branch is the DotaMind vNext clean-slate rewrite. The Legacy V3 baseline is
frozen at Git tag `pre-vnext-rewrite`.

Before architecture or product work, read:

1. `docs/PRODUCT.md`
2. `docs/ARCHITECTURE.md`
3. `docs/ARTIFACTS.md` when work touches large result externalization, Artifact
   schema/storage/search/read, or the current Artifact simplification migration
4. `docs/TOOLS.md`
5. `docs/DATA.md`
6. `docs/EVALS.md`
7. `docs/ROADMAP.md` when the work belongs to a planned phase

The current code may intentionally lag the target documents during an active
migration. Do not preserve Legacy or transitional vNext structure merely because
it already exists.

# Architecture Rules

- The model owns normal business reasoning and decides when to use independent
  Dota capabilities.
- Tools expand the model's observable fact space; do not add scenario-specific
  workflows, routers, or prompt recipes.
- Do not introduce an ExecutionPlan DSL, model-authored evidence obligations, or
  provider-visible orchestration.
- Deterministic code protects validation, canonical identity, authorization,
  provider transport, cross-source resolution, persistence, bounds, and errors.
- Provider-private IDs stay below the model-facing Domain/Artifact boundary.
- Canonical Valve-native IDs may remain directly observable facts.
- A Ref is a locator passed between capabilities, not a wrapper for every Dota
  ID, slot, or event structure.
- Prefer deletion over compatibility shims when replacing transitional vNext or
  Legacy behavior.

# Artifact Rules

Artifacts exist primarily to keep complete large results outside model context
while preserving generic search/read access.

- Treat an Artifact as a canonical JSON-like document substrate, not a second
  Dota object graph.
- Keep Artifact production thin: verified provider facts + necessary canonical
  normalization/composition -> document -> ArtifactStore -> ArtifactRef.
- Do not create construction Ref types for hero IDs, item IDs, ability IDs,
  inventory slots, purchase events, draft events, or similar nested content when
  no cross-capability locator is required.
- Keep static Valve catalog facts separate from dynamic Game Artifact facts.
  Prefer small `catalog.search` / batch `catalog.lookup` capabilities instead of
  duplicating names/localization into every game document.
- Preserve provider-private ID exclusion. Valve match/team IDs, Steam account
  IDs, and hero/item/ability IDs may cross as canonical Dota-native facts.
- `artifact.grep` and `artifact.read` remain generic observation primitives and
  must not learn GameSummary-specific scenario semantics.
- Scope remains generic `ArtifactScopeRef -> ArtifactRef[]`; membership comes
  from already-known navigation ancestry, never from parsing Artifact content.
- Evolve a material Artifact contract through a new schema version rather than
  silently mutating a frozen historical version.

# Development Rules

- Verify the current branch/head and relevant tests before changing behavior.
- Do not add fallback or mock behavior that hides missing integrations or errors.
- Network/provider SDK calls belong only in provider adapters.
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
  future needs.
- Record material decisions as `Decision`, `Reason`, and `Not included` when
  useful for preserving a boundary.

## Identity

- A provider entity -> canonical Domain Ref mapping has one owner and one
  deterministic construction rule.
- Different services must not invent their own hash recipes for the same source
  entity.
- Do not synthesize a formal canonical Ref from weak descriptive signals merely
  to avoid a nullable identity; preserve unresolved/ambiguous identity instead.
- Keep navigation identity separate from Artifact content identity.

## Schemas and data

- Base schemas on verified provider data, committed catalog data, and explicit
  product/architecture contracts.
- Preserve missing-data semantics rather than filling gaps with guesses.
- Static catalog lookup and dynamic recorded game facts are separate fact
  spaces; combine them in the model unless a concrete product requirement
  justifies materializing the static fact into an Artifact.
- Do not add DotaMind-derived gameplay analytics to source-backed Artifacts.

## Delivery and review

- One commit should represent one architecture decision or implementation
  boundary plus its focused tests.
- During the current Artifact simplification, follow the migration order in
  `docs/ARTIFACTS.md`; do not delete the old v4/v5 production path before the new
  schema/path is proven.
- Before review, check layer direction, identity consistency, verified source
  semantics, forbidden provider IDs, missing-data behavior, model-visible tool
  contracts, and the focused tests that protect the change.

Small steps, explicit boundaries, and deletion of unnecessary machinery are
preferred over broad framework-building.
