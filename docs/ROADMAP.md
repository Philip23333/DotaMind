# Roadmap

## Guiding order

Work one capability boundary at a time:

```text
architecture confirmation
  -> one design unit
  -> implementation
  -> focused acceptance
  -> broader regression
```

Do not expand a capability into a provider-routing framework or universal DTO
before a second concrete implementation demonstrates the need.

## Commit 1: clean-slate tool layer

- Establish an artifact-only default model-facing registry baseline.
- Remove legacy domain tools, provider integrations, sample-policy mutation,
  provider prompt rules, and compatibility aliases.
- Preserve generic registry, executor, Controller, execution, tracing,
  persistence, and Artifact runtime primitives.

## Commit 2: semantic esports match search (implemented / under acceptance)

- Add the closed `esports.match.search` capability contract.
- Connect the contract to a thin PandaScore client and match adapter.
- Keep provider query syntax, transport details, and provider-private field
  names below the model-facing tool schema.
- Preserve complete validated match facts in the capability result; the generic
  registry result processor externalizes only oversized responses while keeping
  small observations inline.
- Protect the input/output boundary, request mapping, endpoint selection, and
  registry inventory with focused tests.

## Commit 3: semantic esports league search (implemented / under acceptance)

- Add the closed `esports.league.search` capability for recurring competition
  identity discovery.
- Reuse the existing PandaScore client through a second thin league adapter.
- Keep edition, season, and provider-specific fields out of the league schema.
- Protect one-request mapping, strict `id`/`name` normalization, and the exact
  four-tool registry inventory with focused tests.

## Commit 4: semantic esports series and tournament search (implemented / under acceptance)

- Add closed `esports.series.search` and `esports.tournament.search`
  capability contracts.
- Reuse the existing PandaScore client through explicit series and tournament
  adapters using their collection endpoints.
- Preserve the League → Series → Tournament → Match discovery boundaries while
  keeping provider-private query fields below the model-facing schemas.
- Protect single-request mapping, normalization, contract composability, and
  the exact six-tool registry inventory with focused tests.

## Commit 5: semantic esports team and player search (implemented / under acceptance)

- Add closed `esports.team.search` and `esports.player.search` capability
  contracts for participant identity and current-team discovery.
- Reuse the shared PandaScore client through explicit team and player collection
  adapters using `/dota2/teams` and `/dota2/players`.
- Keep provider query syntax and roster payloads below the model-facing schemas;
  `Team.players` is intentionally omitted from team identity output.
- Inherit the generic Artifact result processor without capability-specific
  externalization logic.
- Protect one-request mapping, normalization, composability, and the exact
  eight-tool registry inventory with focused tests.

## Commit 6: series participant-team capability (implemented / under acceptance)

- Add the closed `esports.series.teams` capability for one known series.
- Use the PandaScore `/dota2/series/{series_id}/teams` collection and normalize
  only participating team identities.
- Keep historical player rosters and exact per-match lineups outside this
  capability's contract.
- Reuse the shared result processor and protect the endpoint path, normalization,
  schema boundary, and nine-tool registry inventory.

## Subsequent capability work

1. Define one closed semantic capability contract.
2. Add its provider implementation and complete source-backed document path.
3. Protect input/output schemas, bounds, source attribution, and failures with
   deterministic tests.
4. Register the capability only after its focused acceptance passes.
5. Remove transitional code once the replacement is accepted.

## Steam player and game-detail capability contracts (contract commit complete)

- Define strict Steam32 inputs for player profile and recent-game observations,
  plus a Valve game-ID input for existing single-game detail.
- Preserve provider provenance and source business objects as JSON while
  keeping Steam accounts separate from PandaScore professional-player IDs.
- Contract models and deterministic acceptance tests are in place. STRATZ and
  OpenDota provider implementations, source-semantic validation, and product
  tool registration remain pending; these capabilities are not yet callable.
- The planned detail path reads an existing game record. Replay submission and
  replay parsing are outside this scope.

## Context Governance: Runtime-driven history compaction

The next phase is defined by
[`agent/context_governance_evidence_lifecycle.md`](agent/context_governance_evidence_lifecycle.md).
Runtime summarizes older execution history, retains recent raw messages, and
commits the current summary and kept boundary together. Bounded FIFO Artifact
locators support rereads. Follow-ups retain effective history with fresh
execution state. Storage remains process-local; restart recovery is excluded.

Implementation follows four stage exits:

1. Session execution records and shared execution/answer context construction.
2. One compaction loop, atomic summary/boundary replacement, and FIFO locators.
3. Full-input pressure, automatic compaction, bounded failure, and one overflow
   compact-and-retry recovery attempt.
4. Esports evaluations and removal of superseded summary/release gates.

Phases one, two, and three are implemented and have passed deterministic
acceptance. The verified workflows cover session records and projections,
atomic compaction, automatic full-request watermark checks for execution and
answering, bounded capacity fallbacks, one provider overflow recovery per user
request, Artifact rereads, product follow-ups, and recovery after a failed
summary candidate. The normal product entry passes the context-window
configuration into the session Runtime; an unset window leaves automatic
capacity governance disabled. These results do not claim real-model quality.

Phase four has not started: evaluate against real esports tasks and real models,
tune parameters, and clean up superseded behavior. Token capacity is an
estimate, provider overflow classification supports only its explicit current
error code, Artifact locators are bounded, summaries may omit information, and
session state remains process-local. The system does not promise to continue
arbitrarily long tasks. No real `.env` value is a project default, and this
roadmap does not imply that a service has been restarted.

No model-directed summary/release tools or general history-search tools are
required by the current design.

## Follow-up: generic tool-result externalization (implemented / under acceptance)

- Attach one session-scoped result processor at registry composition time.
- Keep complete validated non-Artifact outputs in the session Artifact store
  when they exceed the inline bound.
- Return a deterministic bounded structural observation and opaque reference to
  the model while leaving `artifact.read` and `artifact.grep` inline.
- Protect the spill threshold, observation bound, full-result recovery, and
  Artifact-tool bypass with focused tests.

## Product chat: Run State and AssistantTransport (frontend integrated)

The accepted design and acceptance criteria are defined in
[`agent/product_run_state.md`](agent/product_run_state.md). Phase 1 lifecycle
design is approved. The product Run State schema, synchronous projection,
deterministic tests, and service integration with Runtime projection, persistence,
completed-answer retry, and repository replay are implemented. Phase 2 Runtime
lifecycle events, live delta delivery, and the event-to-state adapter are
implemented and validated. The Phase 3 backend AssistantTransport endpoint is
implemented and verified over real loopback HTTP with the official JavaScript
decoder, including live deltas, fallback, persistence, and disconnect
cancellation. The production chat frontend uses `/transport`; the per-thread
runtime registry preserves each connection and message state while switching
threads. Unread counts are session-scoped local state, clear on selection, and
update the sidebar without waiting for a session-list request. Mounted frontend
integration tests cover switching, independent stop, unread clearing, and save
updates. Actual disconnect cancels unfinished generation. Continuation after
disconnect and stream resume are excluded. The obsolete product-chat NDJSON
protocol was removed in Phase 6; the separate Runtime test-run `/runs` stream
remains.
Generation errors replace streamed text with fallback in the same message;
cancellation, disconnection, and save failures have separate semantics.
Started saves use a unified finite application-level budget; timeout preserves the
answer and cache for idempotent lookup/retry. Optional visual metadata failure
does not block canonical answer persistence.
Work one boundary at a time in this order:

1. Define the product state, message identities, history boundary, cancellation,
   persistence, interruption, and retry semantics.
2. Runtime answer-stage/attempt lifecycle events and identities are implemented
   with deterministic tests, primary/degraded answer fragments are delivered
   during the model invocation, and the request-local event-to-state adapter is
   connected to `VNextChatService` persistence, cache retry, and replay.
3. Connect the pure converter and AssistantTransport endpoint through the
   production runtime-provider in one end-to-end path, preserving authorization
   and request idempotency. Implemented.
4. Integrate independent thread runs, messages, history, and standard Markdown
   rendering; defer catalog visual enhancement. Implemented.
5. Implement execution/tool/final presentation and user-controlled folding.
   Implemented with ordered Run State activity and per-message local folding.
6. Complete failure/history regression and remove obsolete product-chat protocol
   code. Implemented; tests use the product state stream directly. The separate
   `/runs` Test Observer event stream remains independent.

First-version final answers stream as the model generates them, following the
requested ChatGPT-style interaction. Waiting for the complete answer or replaying
buffered text with a typing animation does not satisfy this requirement. Include
partial-answer interruption, fallback replacement, and canonical completion
reconciliation in the initial contract and focused checks. Resumable streams,
cross-tab recovery, raw reasoning display, and durable execution recovery are
outside this work. Failure semantics are designed in Phase 1 and tested with
each implementation phase, not postponed until the final regression phase.

## Not planned in the baseline

- a complete domain tool suite before each capability contract is accepted;
- provider selection or routing machinery;
- a universal esports hierarchy or cross-provider DTO;
- hidden provider fetches from Artifact tools;
- scenario-specific workflows or prompt recipes;
- sample-size or provider-specific plan mutation.
