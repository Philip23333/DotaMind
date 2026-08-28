# Roadmap

## Phase 0 — Clean-slate documentation

Status: complete.

Goal: replace the Legacy V3 design tree with a small vNext documentation set.

Acceptance: active vNext work follows the core documents rather than Legacy
orchestration contracts.

## Phase 1 — Native Agent Runtime

Status: complete.

Goal: establish the minimal provider-neutral native tool-calling loop.

Delivered:

- provider-neutral model protocol
- validated tool registry/dispatch
- execution limits, deadlines, cancellation, stable errors
- native streaming
- session-neutral runtime

## Phase 2 — Esports navigation and match resolution

Status: complete, with one identity-correctness follow-up pending.

Goal: make esports discovery and resolved match/game detail useful without
scenario orchestration.

Delivered:

- Series and Match capabilities
- canonical PandaScore navigation semantics
- deterministic PandaScore Game -> Valve match resolution
- OpenDota resolved-game detail

Pending correctness follow-up:

- make PandaScore entity -> Domain Ref construction single-source and fix the
  current divergent SeriesRef recipes before scoped Artifact membership is
  considered reliable

## Phase 2.x — Simplified Artifact corpus

Status: in progress.

Goal: keep complete large game results outside model context while making them
generically searchable/readable, without maintaining a second Dota object graph
inside Artifact construction.

Historical implementation already delivered:

- GameSummary schema versions 3, 4, and 5
- ArtifactStore memory/Redis retention
- deterministic versioned `ArtifactRef`
- automatic resolved-game production from match detail
- `artifact.search`, `artifact.grep`, and `artifact.read`
- generic `ArtifactScopeStore`
- V5 readable PandaScore event context

These contracts proved the externalized-corpus model, but the current production
path became heavier than needed through construction-only Ref wrappers and
catalog enrichment.

### Simplification migration

The next implementation sequence is frozen in `ARTIFACTS.md` and should be
executed incrementally:

1. Stabilize PandaScore navigation identity and SeriesRef reverse mapping.
2. Add minimal local `catalog.search` and batch `catalog.lookup` tools.
3. Define a new simplified GameSummary schema version (expected v6).
4. Keep readable PandaScore event context but store Valve-native hero/item/
   ability IDs directly instead of duplicated catalog names.
5. Replace the construction-Ref/catalog-enrichment graph with thin canonical
   normalization from verified provider models to the v6 document.
6. Switch automatic GameSummary production to v6 while keeping generic
   `artifact.grep/read` contracts.
7. Delete obsolete construction-only refs/resolvers/builders after the new path
   is proven.
8. Validate the composition with real model questions that require navigation,
   catalog lookup, Artifact grep/read, and reasoning without scenario-specific
   runtime code.

Target exploration model:

```text
navigation tools
  -> locate Game / scope

large game facts
  -> ArtifactStore
  -> ArtifactRef

model
  -> artifact.grep / artifact.read
  -> catalog.search / catalog.lookup when static ID meaning is needed
  -> answer
```

Non-goals:

- one Ref type per nested Dota value
- one tool per Artifact section or scenario
- raw provider JSON in model context
- provider-private IDs in Artifacts
- semantic/vector search before demonstrated need
- automatic provider fetch from Artifact search/read
- a separate model-facing produce tool for normal match-detail production

Acceptance:

- complete large game data stays outside model context by default;
- a stored v6 Game document is understandable through generic Artifact tools
  plus small catalog tools;
- Artifact production no longer depends on construction-only Ref/catalog
  enrichment machinery;
- scoped corpus membership uses stable navigation identity;
- representative real-model questions work through capability composition rather
  than hard-coded workflows.

## Phase 3 — Team, player, and static catalog capabilities

Status: team/player complete; minimal catalog tool surface pending as part of the
Artifact simplification.

Delivered:

- PandaScore-backed team search/detail
- PandaScore-backed player search/detail
- shared runtime-scoped TeamRef/PlayerRef navigation identity

Pending:

- `catalog.search`
- bounded batch `catalog.lookup`
- additional team/player capabilities only when real evals show an independent
  fact-space gap

Non-goal: add player-build/performance scenario tools when generic Match,
Artifact, and catalog composition is sufficient.

## Phase 3.5 — vNext Product Integration

Status: complete.

Goal: expose vNext through the existing browser chat product without importing
Legacy orchestration.

Delivered:

- request-bound vNext AgentRuntime streaming endpoint
- browser-owned PostgreSQL session/transcript persistence
- persisted User and Final Assistant dialogue
- process-lifetime shared vNext services
- deterministic visual entity enrichment after the model response

## Phase 4 — Conversation reliability and eval expansion

Status: in progress.

Delivered:

- bounded ConversationContextBuilder over the complete PostgreSQL transcript
- failed-run trace retention and downloadable debugging evidence

Add compaction, durable AgentRun/reconnect/replay, and broader provider-drift
infrastructure only when observed product failures justify them.

## Phase 5 — Product UX

Goal: present facts, sources, uncertainty, and structured data clearly without
moving gameplay reasoning out of the model.

## Phase 6 — Legacy deletion

Goal: remove remaining Legacy paths after vNext replacements are proven.

Acceptance: vNext passes its regression/eval suite without Legacy orchestration
or compatibility shims. The `pre-vnext-rewrite` tag remains the historical
reference.
