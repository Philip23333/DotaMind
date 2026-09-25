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

## Product chat: Run State and AssistantTransport (planned)

The accepted design and acceptance criteria are defined in
[`agent/product_run_state.md`](agent/product_run_state.md). Phase 1 lifecycle
design is approved. The product Run State schema, synchronous projection, and
deterministic projection tests are implemented, but this does not complete Phase
1 end-to-end acceptance or connect the projection to product chat. Phase
2 Runtime event/projection design, Phase 3 transport/converter, and Phase 4
message/history design are approved. Phase 2's Runtime answer lifecycle event
and identity portion, live delta delivery, and a standalone Runtime-to-Run-State
adapter are implemented and independently validated. The adapter is not yet
connected to `VNextChatService` persistence/cache handling; HTTP and frontend
integration remain pending. Phases 3-4 implementation has not started. The
current product protocol does not represent attempt reset, so browser fallback
replacement is not yet supported. Thread switching keeps runs and connections
alive within the page; actual disconnect cancels unfinished generation. Continuation
after disconnect and stream resume are excluded. Generation errors replace
streamed text with fallback in the same
message; cancellation, disconnection, and save failures have separate semantics.
Work one boundary at a time in this order:

1. Define the product state, message identities, history boundary, cancellation,
   persistence, interruption, and retry semantics.
2. Runtime answer-stage/attempt lifecycle events and identities are implemented
   with deterministic tests, primary/degraded answer fragments are delivered
   during the model invocation, and a request-local event-to-state adapter emits
   changed snapshots. Integration with the product chat save/cache path remains
   pending.
3. Connect AssistantTransport and a minimal frontend converter in one end-to-end
   path, preserving authorization and request idempotency.
4. Integrate independent thread runs, messages, history, and standard Markdown
   rendering; defer catalog visual enhancement and retire the old protocol after
   the replacement is accepted.
5. Implement execution/tool/final presentation and user-controlled folding.
6. Complete failure/history regression and remove obsolete code.

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
