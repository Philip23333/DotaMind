# Roadmap

## Phase 0 — Clean-slate documentation

Status: complete.

Goal: replace the Legacy V3 design tree with a small vNext documentation set.

Deliverables:

- Product, architecture, tools, data, evaluation, and roadmap documents
- Retained cross-source match mapping and provider/catalog references
- Collaboration guidance focused on incremental architecture decisions

Acceptance: the vNext documentation is internally consistent and no active
roadmap depends on deleted Legacy design documents.

## Phase 1 — Native Agent Runtime

Status: complete.

Goal: establish the minimal provider-neutral native tool-calling loop.

Deliverables:

- Provider-neutral model protocol
- Tool registry and validated dispatch
- Maximum steps/tool calls, deadlines, cancellation, and stable runtime errors
- Native text streaming
- In-memory, session-neutral execution

Acceptance: multi-turn native tool calls work without ExecutionPlan,
EvidenceGraph, scenario routes, or a durable transcript dependency.

## Phase 2 — Competition and match

Status: complete.

Goal: make current esports discovery and match detail useful.

Deliverables:

- Competition and schedule capabilities
- Match search and detail capabilities
- Deterministic identity and cross-source match resolution

Acceptance: deterministic competition and match capability evals pass, and live
provider smoke tests succeed without claiming ambiguous mappings as facts.

## Phase 2.x — Artifact Foundation

Status: in progress.

Goal: establish bounded, reusable artifact production and retrieval boundaries
before expanding scenario capabilities.

Implemented deliverables:

- `GameSummaryArtifact` schema version 3, frozen as a historical schema
- `GameSummaryArtifact` schema version 4 with catalog-backed English and Chinese
  entity identity facts for heroes, items, and abilities
- Commit 3 — OpenDota-to-`GameSummaryArtifact` construction pipeline
- Commit 3.5 — Artifact Production & Store Integration
  - coordinate canonical game identity -> provider fetch -> artifact construction
    -> `ArtifactStore.put` -> `ArtifactRef`
  - deterministic `ArtifactRef` derived from canonical artifact identity
  - request/response canonical match identity validation
  - no cache/TTL/refresh policy in this commit
  - keep artifact production outside Agent Runtime and model-facing tools
- Commit 4 — Artifact Retrieval Capability
  - `matches.get_detail` exposes canonical `valve_match_id` and guarantees
    production and storage for every resolved game before success
  - bounded `artifact.search` lookup over canonical Valve match IDs
  - bounded `artifact.read` outline and structural path views with list limits
  - six-tool registry with artifact retrieval kept separate from production
- Commit 5 — Artifact-driven Agent Evals
  - fixture-backed real-model evaluation through the real AgentRuntime and
    six-tool registry
  - deep artifact fact exploration, conversation follow-up reuse, and
    missing-data grounding behavior

Artifact quality metadata persistence is not part of Commit 3.5.

Redis-backed ArtifactStore is now implemented as a later retention boundary:
process-restart persistence with deterministic versioned keys and a seven-day
TTL, without adding a producer cache-hit or freshness policy.

- Canonical esports navigation: `League -> Series -> Tournament -> Match -> Game`,
  including opaque League/Series/Tournament refs and Series-named discovery tools.
- `GameSummaryArtifact` schema version 5, preserving V4 game facts plus
  already-known readable esports event context without provider IDs or refs.
- Generic `ArtifactScopeStore` with seven-day-aligned memory/Redis contracts;
  successful V5 production registers known esports navigation memberships.
- Generic `artifact.grep` breadth search with optional opaque scope and explicit
  `materialized_only` coverage.

Planned / pending deliverables:

- Reduced default tool context through bounded retrieval.

The intended exploration model is breadth-to-depth and model-first:

    generic corpus search
      -> bounded matches + ArtifactRef + structural path
      -> model chooses what matters
      -> artifact.read
      -> bounded detailed evidence

Search is treated as an observation primitive, analogous to grep over a
structured artifact corpus. It should not encode user scenarios such as
player-plus-hero builds, tournament strategy, or one search projection per
artifact type. New artifact types should become searchable through their
canonical serialization; performance may later move from corpus scanning to a
generic index without changing the model-facing contract.

The Phase 2.x delivery order separates three responsibilities deliberately:
Commit 3 constructs a canonical artifact, Commit 3.5 produces and stores it,
and Commit 4 retrieves bounded views of stored artifacts. Production and
retrieval are application/data-layer responsibilities rather than Agent Runtime
stages.

Non-goals:

- Adding a tool for every artifact section or user scenario
- Exposing raw provider JSON, full match dumps, large records, or provider IDs
  to the model
- Requiring a fixed retrieval sequence
- Making Agent Runtime responsible for creating, storing, refreshing, expiring,
  or otherwise owning artifact lifecycle
- Creating programmer-authored discovery projections or search adapters for
  each artifact type when generic canonical-content search is sufficient
- Letting artifact search implicitly populate its corpus from providers

Acceptance: the artifact production and retrieval contracts are implemented and
evaluated with explicit bounds, coverage, missing-data behavior, and canonical
serialized views. The next breadth-search increment is accepted only if the
same search primitive can operate across future canonical artifact types
without embedding GameSummary-specific business dimensions in its public
contract.

## Phase 3 — Team, player, and catalog

Status: complete.

Goal: make conversational team and player research useful after the retrieval
boundary is proven.

Implemented in Commit 1:

- PandaScore-backed team search and detail capabilities
- PandaScore-backed player search and detail capabilities
- Provider-neutral Team/Player domain models with nullable source facts
- Shared runtime-scoped opaque TeamRef/PlayerRef identity across match, team,
  and player capabilities

Planned / pending deliverables:

- Cross-capability Agent evaluation across Team, Player, Competition, Match,
  Game, and Artifact capabilities
- Additional Team, Player, or catalog capabilities only when real evaluations
  demonstrate a concrete missing fact boundary

These demand-driven capability additions do not block Phase 3.5.

Non-goals:

- Adding team-specific match capabilities when `matches.*` already covers the
  use case
- Adding player performance or build capabilities before evaluating
  composition through `matches.*` and `artifact.*`
- Adding one tool per user scenario
- Introducing scenario-specific runtime workflows

Acceptance: real and fixture-backed Agent evaluations demonstrate that the
model can compose Team, Player, Match, Game, and Artifact capabilities for
representative research questions without requiring scenario-specific tools
or fixed workflows. New capabilities are added only for demonstrated coverage
gaps.

## Phase 3.5 — vNext Product Integration

Status: complete.

Goal: expose the current vNext Agent through the existing browser chat product
without importing Legacy orchestration into the vNext execution path.

Deliverables:

- Reuse the existing Next.js / assistant-ui chat and browser-owned PostgreSQL
  session/transcript persistence.
- Add a request-bound vNext `AgentRuntime` streaming endpoint at
  `POST /api/v1/chat/sessions/{session_id}/messages`.
- Persist only durable User and Final Assistant dialogue, including across
  browser refreshes.
- Share process-lifetime vNext services and the in-memory ArtifactStore across
  web requests.
- Verify browser end-to-end product smoke behavior.

Non-goals:

- Durable AgentRun lifecycle, Redis event replay, resume, or checkpoint recovery
- Context compaction or summarization
- Tool-result or artifact persistence
- New domain capabilities or Legacy deletion

Acceptance: users can create, resume, refresh, and continue browser
conversations backed by the vNext AgentRuntime while the frontend remains
independent of Agent, Tool, Artifact, and provider internals.

## Phase 4 — Conversation reliability and eval expansion

Goal: harden long-lived conversations based on observed needs.

Implemented deliverables:

- Conversation context construction boundary between the full PostgreSQL
  transcript and vNext model input
- Bounded recent, complete-turn context: at most 12 persisted turns and 40,000
  historical text characters, while retaining the complete durable transcript
- Failure-trace observability: browser-owned failed-run traces retained in Redis
  for 72 hours, with expiring ZIP downloads that include application-visible
  execution evidence and still-available referenced artifacts.

Planned / pending deliverables:

- Lightweight conversation compaction only when observed necessary
- Durable AgentRun, reconnect, and recovery semantics only when product usage
  demonstrates a need
- Durable event semantics and expanded regression and provider-drift evals only
  where they solve an observed need

Acceptance: durable conversation context, recovery, and cancellation behavior
have repeatable tests; additional infrastructure is added only when the need is
demonstrated.

## Phase 5 — Product UX

Goal: present facts clearly in chat and structured match views.

Proposed deliverables:

- Structured rendering where it is more reliable than generated prose
- Source, freshness, and uncertainty presentation

Acceptance: users can understand what is fact, inference, or unavailable data.

## Phase 6 — Legacy deletion

Goal: remove remaining Legacy runtime paths after their replacements are proven.

Acceptance: vNext passes its eval suite without Legacy orchestration or
compatibility shims. Git tag pre-vnext-rewrite remains the historical reference.
