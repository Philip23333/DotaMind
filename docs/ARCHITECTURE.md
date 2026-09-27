# Architecture

## Status

The tool layer is in a clean-slate rebuild. The default LLM-facing registry
currently contains the generic Artifact tools and the closed
`esports.league.search`, `esports.series.search`,
`esports.series.teams`, `esports.tournament.search`,
`esports.match.search`, `esports.team.search`, and `esports.player.search`
capabilities. When explicitly enabled and discovered during application
startup, it also contains `web.search`, backed by Tavily's remote
`tavily_search` MCP tool.
Additional domain capabilities are introduced later as independent contracts.

## Principles

- The model chooses which broad capability observations to combine.
- Deterministic code owns validation, bounds, persistence, and stable errors.
- Provider adapters remain below capability contracts; the current Artifact
  path receives each capability's validated public output rather than raw
  provider transport payloads.
- Temporary Artifacts externalize complete large logical tool responses without
  becoming domain entities or a searchable corpus.
- A provider-private identifier is evidence, not a model-facing navigation
  language, unless a future capability explicitly defines that input.

## System boundary

```text
User
  -> Product Chat API
  -> Agent Runtime
  -> LLM
       <-> artifact.grep / artifact.read
             -> session Artifact store
       <-> esports.league.search
             -> league capability contract
             -> PandaScore adapter/client
             -> league observations
       <-> esports.series.search
             -> series capability contract
             -> PandaScore adapter/client
             -> series observations
       <-> esports.series.teams
             -> series participant-team capability contract
             -> PandaScore adapter/client
             -> series team observations
       <-> esports.tournament.search
             -> tournament capability contract
             -> PandaScore adapter/client
             -> tournament observations
       <-> esports.match.search
             -> match capability contract
             -> PandaScore adapter/client
             -> validated match observations
       <-> esports.team.search
             -> team capability contract
             -> PandaScore adapter/client
             -> team identity observations
       <-> esports.player.search
             -> player capability contract
             -> PandaScore adapter/client
             -> player identity/current-team observations
       <-> web.search (optional)
             -> discovered remote JSON Schema / local validation
             -> Tavily MCP adapter
             -> official MCP SDK Streamable HTTP session
             -> source-preserving search observations
       oversized tool result
             -> generic result processor
             -> complete validated logical tool response in a session Artifact
             -> bounded observation
```

Future domain capabilities follow this seam:

```text
Model
  -> semantic Tool / capability contract
  -> Capability Service
  -> Provider implementation
  -> Provider Adapter / transport
  -> complete validated capability result
       -> bounded observation when oversized
```

The model-facing contract never exposes wire routes, credentials, pagination
syntax, or transport-private IDs. A single provider does not justify a router or
plugin framework.

The optional web-search integration is initialized asynchronously in the API
lifespan before Runtime construction. Synchronous/offline composition performs
no MCP I/O. Startup discovers and validates the exact remote search capability;
each later search opens and closes a separate authenticated MCP session. The
bearer credential is confined to the transport header, and discovery or request
failures do not disable the independent PandaScore services.

## Tool registry boundary

`ToolRegistry`, `ToolDefinition`, and `ToolExecutor` are generic runtime
primitives. The default builder lives in the composition root and explicitly
registers Artifact tools plus accepted domain capabilities. A generic result
processor is attached at registry composition time: it stores complete
oversized non-Artifact outputs and returns bounded observations, while each
Artifact retrieval tool opts out explicitly. Domain modules must not own the
application registry builder, and removed capabilities must not be kept as
aliases or hidden registrations.

The current esports boundaries are `esports.league.search`,
`esports.series.search`, `esports.tournament.search`,
`esports.series.teams`, `esports.match.search`, `esports.team.search`,
and `esports.player.search`. Each capability owns
semantic inputs and outputs, while its thin PandaScore adapter translates those
inputs into one provider request and normalizes validated facts. All six
adapters share one `PandaScoreClient` at composition time; provider routes and
query parameter names stay below the model-facing schemas.

The adapter tree is intentionally explicit:

```text
PandaScoreClient
  ├── LeagueAdapter
  ├── SeriesAdapter
  ├── TournamentAdapter
  ├── MatchAdapter
  ├── TeamAdapter
  └── PlayerAdapter
```

Provider-private `serie_id` is translated to semantic `series_id` only inside
PandaScore adapters.

## Artifact boundary

Artifacts are temporary, process-local, session-owned JSON-like documents. Each
oversized response receives a fresh opaque reference. `artifact.read` and
`artifact.grep` accept one exact reference and never fetch a provider or
perform business aggregation. The Artifact content is the complete validated
logical tool response; the bounded model observation is derived separately by
the generic result processor for ordinary tools. A stored ref is not
automatically restored into a later turn's dialogue context.

## Runtime boundary

The Controller owns decision shape, schema adherence, reference validation, and
capability-boundary errors. The execution runtime owns budgets, retries,
tracing, and persistence. Complete-request context capacity and automatic
compaction govern effective history; there is no independent cumulative Raw
admission budget. Execution has no step-count ceiling; Runtime retains
step numbering for traces, while the execution deadline, cancellation, plan
completion, and existing context-capacity or error exits control its lifecycle.
Steps-pressure calculations remain available for isolated tests, but production
Runtime does not supply a step budget.

Execution and answering have separate wall-clock deadlines. The execution
deadline defaults to 300 seconds and the answer deadline defaults to 60 seconds;
each can be configured from the repository-root `.env` with
`DOTAMIND_EXECUTION_DEADLINE_SECONDS` and
`DOTAMIND_ANSWER_DEADLINE_SECONDS`. Answer context preparation, compaction and
recovery, the primary response, and a degraded response share one answer
deadline. A degraded attempt never resets that budget, and an exhausted budget
uses the existing no-model fallback. Runtime prompts are ephemeral request
projections: execution prompts include time pressure and available tools, while
answer prompts include their own time-pressure snapshot and say tools are
unavailable.

`QueryContext` is intentionally empty until a real cross-tool concern is
designed. The model-authored `ExecutionPlan` is validated as received; no
provider-specific or sample-size mutation is applied afterward.

## Product chat state and transport

Runtime events are projected into a product-owned Run State before transport.
Execution outcome, canonical answer readiness, and dialogue persistence are
separate facts; a storage failure does not turn a completed Runtime into a failed
execution. Runtime must not depend on assistant-ui or presentation state.

The production chat path uses AssistantTransport for state replication and a
frontend converter for message integration. A page-lifetime registry owns each
thread's connection and local Run State; changing the selected thread does not
cancel another thread's stream. The sidebar's session unread indicators are
browser-local and update independently of session-list reloads. Process activity
is presentation-only: it reads ordered Run State metadata while canonical answer
text remains in the assistant message body. The obsolete product-chat NDJSON
route and its event adapters have been removed. The separate `/runs` Runtime test
event stream remains for the Test Observer and is not a chat transport. The state
contract, ephemeral activity, canonical
history/metadata boundary, and phase acceptance are owned by
[`agent/product_run_state.md`](agent/product_run_state.md).

## Migration order

1. Keep the Artifact baseline green.
2. Add one domain capability with its own input/output contract and tests.
3. Register it explicitly after its boundary is accepted.
4. Delete transitional code instead of preserving compatibility shims.

## Rejected designs

- provider-named model tool namespaces;
- one universal open resource selector;
- a universal cross-provider business DTO;
- transport-private IDs as general capability inputs;
- scenario-specific workflows embedded in the generic registry;
- provider routers before a second concrete implementation exists;
- Artifact corpus discovery or hidden provider fetches.

## Steam player and game-detail boundaries

The `capabilities/player` and `capabilities/game` contracts define closed
inputs, provenance, and source-shaped JSON outputs. `player.profile` and
`player.recent_games` share the STRATZ GraphQL client and register only when a
STRATZ token is configured. The recent-games adapter sends `take`,
`orderBy: DESC`, and `playerList: SINGLE`, validates the outer and row Steam32
identities, and preserves selected match/player source objects as JSON. The
historical schema inventory identifies `DESC` as date ordering; local sorting
only stabilizes the returned order after STRATZ has selected the bounded
subset. A live cross-check for match `8960882635` returned the same ID, start
time, and duration from STRATZ `match(id)` and OpenDota. A live `player.matches`
query for one participant requested the newest 20 with `orderBy: DESC`; raw
STRATZ timestamps were nonincreasing and each row contained only that account.
The supplied match predates that sample and was not among those 20. This is
single-account sample evidence, not a guarantee for every account or general
provider availability. `game.detail` is implemented by an opt-in OpenDota
adapter. It requires the returned `match_id` to match the requested Valve ID,
checks known fields only when present, and preserves the complete source object
for the generic Artifact processor. Missing process data does not trigger
replay parsing. OpenDota composition and registry construction are network-free.
Steam32 and PandaScore player identities remain separate unless a future
evidence-backed identity capability is designed.

The account-to-game workflow is composed by the existing model-driven Runtime,
not a dedicated player-analysis pipeline. `player.recent_games` supplies the
bounded list, `game.detail` receives only a selected Valve game ID, and the
player row is located by exact `account_id`. Existing conversation history and
generic Artifact handling support ordinal follow-ups and large details; no
second session store or automatic fetch of every listed match is introduced.
The local `catalog.lookup` capability resolves hero/item display labels from
the bundled Valve snapshot without changing provider observations or making
network requests.
