# Roadmap

## Phase 0 — Legacy freeze and documentation reset

Status: complete for documentation.

Goal: stop Legacy V3 architecture from constraining vNext design.

Deliverables:

- Git tag pre-vnext-rewrite freezes the Legacy baseline.
- The active documentation tree contains only vNext core documents and
  high-cost reference facts.
- AGENTS.md no longer requires Legacy V3 planning contracts.

Non-goal: claiming that Legacy runtime code has already migrated.

## Phase 1 — Minimal agent runtime

Status: complete.

Goal: replace Legacy orchestration with a thin model-to-tool loop.

Deliverables:

- Provider-neutral model message protocol
- Tool registration, schema validation, and dispatch
- Step and tool-call budgets, request deadlines, cancellation, basic trace, and
  streaming
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

Status: planned.

Goal: establish a bounded, reusable artifact and retrieval boundary before
expanding scenario capabilities.

Proposed deliverables:

- Artifact contract and canonical artifact model
- Artifact Store contract and backend boundary
- `GameSummaryArtifact v0`
- Proposed `artifact.search` and `artifact.read` capabilities
- Bounded tool responses using summaries, canonical references, coverage, and
  artifact references
- Reduced default tool context through bounded retrieval

Non-goals:

- Adding a tool for every artifact section or user scenario
- Exposing raw provider JSON, full match dumps, large records, or provider IDs
  to the model
- Requiring a fixed retrieval sequence
- Claiming that artifact storage or the new retrieval tools are implemented

Acceptance: the artifact and retrieval contracts are implemented and evaluated
with explicit bounds, coverage, missing-data behavior, and conversation reuse.
This phase is not complete merely because the documents or interfaces exist.

## Phase 3 — Team, player, and catalog

Goal: make conversational team and player research useful after the retrieval
boundary is proven.

Proposed deliverables:

- Team search, schedule, and roster capabilities
- Player record, performance, and match-build capabilities
- Hero and item catalog capabilities

Acceptance: the player and contextual follow-up evals pass with explicit
coverage and parse-data limits.

## Phase 4 — Conversation reliability and eval expansion

Goal: harden long-lived conversations based on observed needs.

Proposed deliverables:

- PostgreSQL session transcript, AgentRun persistence, and bounded context
  strategy
- Reconnection and recovery semantics, plus a production retry policy when
  demonstrated necessary
- Durable event semantics and expanded regression and provider-drift evals only
  where they solve an observed need

Acceptance: durable conversation context, recovery, and cancellation behavior
have repeatable tests; additional infrastructure is added only when the need is
demonstrated.

## Phase 5 — Product UX

Goal: present facts clearly in chat and structured match views.

Proposed deliverables:

- Chat interaction and streaming presentation
- Structured rendering where it is more reliable than generated prose
- Source, freshness, and uncertainty presentation

Acceptance: users can understand what is fact, inference, or unavailable data.

## Phase 6 — Legacy deletion

Goal: remove remaining Legacy runtime paths after their replacements are proven.

Acceptance: vNext passes its eval suite without Legacy orchestration or
compatibility shims. Git tag pre-vnext-rewrite remains the historical reference.
