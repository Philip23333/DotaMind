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

Goal: replace Legacy orchestration with a thin model-to-tool loop.

Deliverables:

- Provider-neutral model message protocol
- Tool registration, schema validation, dispatch, budgets, cancellation, trace,
  and streaming
- Persistent messages and a minimal run record

Acceptance: multi-turn native tool calls work without ExecutionPlan, EvidenceGraph,
or scenario routes.

## Phase 2 — Competition and match

Goal: make current esports discovery and match detail useful.

Deliverables:

- Competition and schedule capabilities
- Match search and detail capabilities
- Deterministic identity and cross-source match resolution

Acceptance: the tournament-status and match-detail evals pass against live
provider data without claiming ambiguous mappings as facts.

## Phase 3 — Team, player, and catalog

Goal: make conversational team and player research useful.

Deliverables:

- Team search, schedule, and roster capabilities
- Player record, performance, and match-build capabilities
- Hero and item catalog capabilities

Acceptance: the player and contextual follow-up evals pass with explicit coverage
and parse-data limits.

## Phase 4 — Conversation reliability and eval expansion

Goal: harden long-lived conversations based on observed needs.

Deliverables:

- Durable session transcript and bounded context strategy
- Error, timeout, cancellation, and retry behavior
- Expanded regression and provider-drift evals

Acceptance: conversation context and cancellation behavior have repeatable tests;
additional infrastructure is added only when the need is demonstrated.

## Phase 5 — Product UX

Goal: present facts clearly in chat and structured match views.

Deliverables:

- Chat interaction and streaming presentation
- Structured rendering where it is more reliable than generated prose
- Source, freshness, and uncertainty presentation

Acceptance: users can understand what is fact, inference, or unavailable data.

## Phase 6 — Legacy deletion

Goal: remove remaining Legacy runtime paths after their replacements are proven.

Acceptance: vNext passes its eval suite without Legacy orchestration or
compatibility shims. Git tag pre-vnext-rewrite remains the historical reference.
