# Project Direction

This branch starts the DotaMind vNext clean-slate rewrite. The Legacy V3
baseline is frozen at the Git tag pre-vnext-rewrite.

Before architecture or product work, read:

1. docs/PRODUCT.md
2. docs/ARCHITECTURE.md
3. docs/TOOLS.md
4. docs/DATA.md
5. docs/EVALS.md
6. docs/ROADMAP.md when the work belongs to a planned phase

The current code is Legacy until it is deliberately replaced. The documents
describe vNext TARGET architecture. Do not treat old code as a vNext
compatibility contract.

# Architecture Rules

- The model owns normal business reasoning and decides when to use domain tools.
- Do not add scenario-specific workflows, routers, or prompt recipes.
- Do not introduce an ExecutionPlan DSL, model-authored evidence obligations, or
  provider-visible tool orchestration.
- Agent-visible tools express independent domain capabilities; provider ID
  conversion, cross-source mapping, and normalization stay below the tool layer.
- Scenario-specific behavior belongs in EVALS.md, not in runtime branches.
- Deterministic code protects validation, identity, authorization, transport,
  timeout, cancellation, persistence, and data integrity boundaries.
- Prefer deletion over compatibility shims when replacing Legacy behavior.

# Development Rules

- Verify the current working tree and relevant tests before changing behavior.
- Do not add fallback or mock behavior that hides missing integrations or errors.
- Network and provider-SDK calls belong only in provider adapters. Domain
  services orchestrate those adapters and never call upstream APIs directly.
- Run focused tests for every behavior change and report only checks that ran.
- Update a core document only when its long-term product or architecture contract
  changes. Do not maintain daily progress snapshots or an in-repository archive;
  Git history, commits, and tags hold implementation history.
- Keep reference/ for facts that are expensive to rediscover from providers or
  cross-source testing. Revalidate volatile provider facts before relying on them.

# Agent Development Guidelines

## Required design flow

- Follow this order: overall architecture confirmation, major modules, one
  design unit at a time, implementation, then acceptance.
- Before a new phase, state its goal, relationship to the system, current
  scope, and explicitly deferred items. Do not design all schemas, interfaces,
  implementation, and future expansion in one pass.
- Split each module into its major parts, then discuss and settle one part
  independently before introducing the next. Confirm scope, non-goals, and
  layer boundaries before changing code.
- Prefer the smallest design that satisfies a verified requirement. Do not add
  abstractions, fields, extension points, or workflows for hypothetical needs.
- Record material design discussions as `Decision`, `Reason`, and `Not
  included`, so later work can preserve deliberate boundaries.

## Schemas and artifacts

- Base Domain and Artifact schemas on verified provider data, committed catalog
  data, and documented product or architecture contracts. Do not infer fields
  from names, examples, or anticipated provider behavior.
- An Artifact is provider-neutral canonical domain data, not a provider DTO,
  database model, or API response. Exclude raw payloads, provider-private IDs,
  adapter metadata, storage and cache state, DotaMind-derived analytics, and
  presentation fields. Canonical native domain IDs may cross it when appropriate.
- Evolve schemas only for source-backed facts with clear semantics and a
  concrete consumer. Preserve null, empty-collection, and fixed-structure
  contracts. Prefer a new artifact version to pre-adding empty or speculative
  future fields or generic abstractions.

## Delivery and review

- Keep the normal delivery order explicit: schema, normalization, storage,
  runtime composition, then tool surface. Each commit covers one layer or
  boundary only; do not combine multi-layer changes in a single commit.
- Before review, check scope, imports and layer direction, verified source
  semantics, forbidden fields, missing-data behavior, and the focused tests
  that protect the changed contract. Confirm that durable contract changes are
  synchronized with the relevant documentation.

## Example: GameSummaryArtifact

1. Verify the provider facts, catalog mappings, identity namespaces, and
   missing-data semantics; define the canonical schema and its tests.
2. Add the schema contract alone, without provider parsing, storage, runtime,
   or tools.
3. Add normalization only after its source mapping rules are verified.
4. Integrate storage, then bounded runtime and tool views, as later independent
   changes with their own review checks.

Small steps, clear boundaries, explicit decisions, and incremental
implementation are preferred over broad, combined changes.
