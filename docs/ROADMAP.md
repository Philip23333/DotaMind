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

## Commit 9: shared local entity-name resolver

- Add a code-internal synchronous component that resolves explicitly selected
  hero, item, and ability IDs through an injected local
  `DotaCatalogRepository`.
- Return each supplied ID, exact catalog names when found, explicit unknown entries,
  and the repository snapshot version. Validate the complete batch before any
  repository access; preserve first-seen order while deduplicating lookups.
- Keep source-field extraction in each business capability. This component does
  not scan payloads, infer IDs, call providers, or register in `ToolRegistry`.
- **Implemented; integration pending:** hero-guide and `game.detail` have not
  yet adopted the resolver, and neither output contract has changed.

## Subsequent capability work

1. Define one closed semantic capability contract.
2. Add its provider implementation and complete source-backed document path.
3. Protect input/output schemas, bounds, source attribution, and failures with
   deterministic tests.
4. Register the capability only after its focused acceptance passes.
5. Remove transitional code once the replacement is accepted.

## Hero guides (cache query, serial executor, and operator CLI implemented; timer deployment pending)

The internal query DTOs and two fixed raw Sven fixtures are implemented and
covered by offline tests. A synchronous, bounded D2PT HTTP client is also
implemented and tested with a fake opener; those tests make no live request. The
`RedisHeroGuideCache` is implemented as an injected, offline-testable component.
It stores exact response bytes, parsed source rows, and DTO projections in
whole-snapshot Redis hashes without TTL; failed attempts retain the last good
snapshot. Its tests use fake Redis and do not verify deployed AOF/restart
persistence. The application injects its existing Redis connection into the
cache and registers the cache-only `hero.guide` tool. A Service combines
independent Pub and Pro source states, filters Pro examples by position, applies
section projections, and exposes pre-projection totals. Cache misses do not
trigger D2PT requests. The internal `HeroGuideRefresher` fetches the hero list
once and requests Pub positions 1 through 5, then Pro once, for each hero in
source order. Client calls are sequential and followed by a one-second wait;
successful responses are parsed and published as whole snapshots, while a fetch
or parse failure records partition attempt metadata and preserves its prior
snapshot. Cache write errors abort the run. An operator-only CLI invokes the
executor using the API container's `DOTAMIND_REDIS_URL`, with a non-blocking
process lock shared among CLI invocations in that one container. A systemd daily
timer template invokes the same command, but it is not installed or enabled. The
CLI is not a public endpoint or model-facing tool, and application startup is not
wired to refresh. No real full refresh has populated the cache. The one-time endpoint
probe verified non-empty sample responses only. Source evidence and its limits are documented
in [`reference/d2pt.md`](reference/d2pt.md).

Implementation and acceptance proceed in this order:

1. **Complete:** define the guide DTO and source boundaries, and pin the
   observed Pub and Pro response bodies as byte-for-byte test fixtures. Contract
   and fixture-integrity tests run offline.
2. **Complete:** implement the bounded D2PT fetch client with deterministic
   injected-opener tests for request shape, transport failures, response bounds,
   and minimal validation. These tests do not call D2PT.
3. **Complete:** implement and fixture-test separate Pub and Pro parsers. Pub
   supplies the primary guide; Pro contributes only examples from
   `recent_matches`. Parser tests use the fixed samples and local constructed
   cases, not live provider requests.
4. **Complete:** implement the standalone persistent cache retaining original
   response bytes, complete parsed source rows, and DTO projections, with atomic
   whole-snapshot replacement, old-value retention on failure, and explicit
   valid-empty records. Publish Pub by hero plus position and Pro by hero. The
   cache uses no TTL; freshness and Pro position filtering belong to the query
   Service.
5. **Complete:** add the cache-only `hero.guide(hero_id, position, section)`
   query capability and register it only when the application provides the
   existing Redis cache dependency. Query registration does not populate cache.
6. **Complete: serial refresh executor.** Use one hero-list response in source
   order, then five Pub position requests and one Pro request per hero. Wait one
   second after every response or D2PT error, parse before publishing, retain the
   last good partition on fetch/parse failure, and abort on cache write failure.
   Offline tests use fake clients, clocks, sleeps, and Redis; no provider or
   production cache was contacted.
7. **Complete in repository; deployment pending:** add the operator CLI, a
   non-blocking per-container process lock, and systemd service/timer templates
   for a daily 03:00 Asia/Shanghai run. The template remains uninstalled and
   disabled until deployment is explicitly configured. The lock is not
   distributed; multi-container refresh coordination is not supported. The
   operator command and timer call the same CLI entry point; neither refreshes
   during application startup or a `hero.guide` query.
8. Install and verify the timer in the target deployment, then verify a real full
   refresh over the intended configured coverage, then run a
   separate real-model answer evaluation. Sample-fixture acceptance, offline
   executor/CLI tests, provider refresh, and answer quality are separate results.

Do not force-match Pub item builds to skill sequences, derive recommendation
routes from Pro aggregates, manufacture a fixed number of examples, or infer
statistical meaning that the source does not establish. Local choices such as
Pub alternative thresholds, list merging/deduplication, and mapping integer
positions to source-specific strings are resolved within their implementation
stage. The DTO input position is already defined as a strict integer from 1
through 5.

## Steam player and game-detail capabilities

- Define strict Steam32 inputs for player profile and recent-game observations,
  plus a Valve game-ID input for existing single-game detail.
- Preserve provider provenance and source business objects as JSON while
  keeping Steam accounts separate from PandaScore professional-player IDs.
- `player.profile` and `player.recent_games` are implemented through the shared
  STRATZ GraphQL client and register only when `DOTAMIND_STRATZ_TOKEN` is
  configured. Deterministic tests use local HTTP mocks. The profile query
  itself has not been live-verified. Recent games request an explicit
  date-descending bounded sample, validate the target player row, and preserve
  source match data for Artifact handling.
- A live spot check of match `8960882635` found matching STRATZ `Match.id` and
  OpenDota `match_id`, with matching start time and duration. A raw query for
  one participant returned 20 `player.matches` rows with nonincreasing
  timestamps under `orderBy: DESC`, each containing only that account. The
  supplied match predates that bounded sample. This is sample evidence, not a
  universal ordering or provider-availability guarantee.
- `game.detail` is implemented through an opt-in OpenDota client and adapter;
  it registers only when `DOTAMIND_OPENDOTA_ENABLED=true`. It validates returned
  `match_id` identity, preserves the complete source object, and uses generic
  Artifact handling. It does not submit or poll replay parsing. Deterministic
  HTTP-mock tests do not establish live OpenDota availability. The prior
  `8960882635` cross-source ID check remains single-match evidence only.

The account-to-game workflow is covered with deterministic Runtime composition:
the agent can continue from an account's bounded recent-games list to one
selected match, locate the exact account row, resolve known hero/item labels
from the local Valve catalog, and keep the prior list available for ordinal
follow-ups. This verifies scripted orchestration only, not real-model tool
selection or answer quality. Real provider/model evaluation remains separate.

## Optional Tavily MCP web search (implemented; live provider call unverified)

- Add the opt-in `web.search` capability through the official Python MCP SDK
  and Streamable HTTP, with the remote `tavily_search` schema discovered at API
  startup and validated locally.
- Keep credentials in the bearer transport header and keep MCP transport,
  provider adaptation, generic ToolRegistry validation, and Artifact handling
  at their existing boundaries.
- Expose only search; extraction, crawling, research, persistent MCP sessions,
  automatic rediscovery, and automatic retries remain out of scope.
- Deterministic tests use local sessions and fakes. A real Tavily MCP request
  has not been run as part of this change; use the explicit smoke command only
  when a live call is intended.

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
