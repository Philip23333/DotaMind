# Architecture

## Status

This is the vNext target architecture. The checked-out Legacy code does not
claim to implement it until each replacement is deliberately delivered.
The artifact construction, production/store, and bounded retrieval boundaries
are implemented for the current GameSummary capability.

## Principles

- The model owns ordinary business reasoning: it decides what information is
  needed, which domain capabilities to call, whether more data is useful, and
  when to answer.
- Deterministic application code owns hard boundaries, with each boundary kept
  in its proper layer rather than folded into the agent runtime.
- Tools expose independent Dota domain capabilities, never provider plumbing or
  a complete scenario workflow.
- Domain services answer what an entity is. Retrieval services answer what data
  is available and how to obtain a bounded view of it.
- Canonical domain data may be large, but model context remains bounded by
  default. Storage is not a responsibility of the model.
- Scenarios are evaluated as behavior, not encoded as runtime routes.

## System boundary

    User
      -> Chat / API
      -> Agent Runtime
      -> LLM <-> Dota Agent Tools / Capabilities
                   -> Domain / Retrieval Layer
                   -> Artifact Store
                   -> Provider Adapters
                   -> Raw Sources

The API owns authentication and request ownership. The runtime owns model
messages, tool dispatch, general limits, request deadlines, cancellation, and
trace or streaming events. The Domain / Retrieval Layer owns Dota identity,
availability, cross-source resolution, normalization, composition, and
bounded views. The Artifact Store retains normalized canonical data that should
not automatically enter model context; its contract exists independently from
the application production and retrieval integrations. Provider Adapters own
upstream HTTP or SDK transport, provider authentication, and provider schemas.
Raw Sources are external provider systems and are never model-facing
contracts.

Identity and availability are separate concerns. Domain services answer
"what entity is this?" and produce canonical references. Retrieval services
answer "what data is available, with what coverage, and how can it be
obtained?" A valid entity reference does not imply that a complete artifact is
available, and an available artifact does not redefine entity identity.

This boundary is a dependency description, not a model-authored or mandatory
call sequence. The runtime does not know what a tournament, player build, or
match-detail scenario is, and it does not own the artifact lifecycle.

## Agent loop

The initial runtime is a thin native tool-calling loop:

    messages
      -> model response
      -> final answer, or tool calls
      -> validated parallel-safe tool execution
      -> tool-result messages
      -> model continuation

It enforces maximum steps, maximum tool calls, deadlines, cancellation,
streaming, and stable error reporting. It does not use an ExecutionPlan DSL,
required-evidence DSL, fixed result destinations, or scenario-specific replan
protocol. Fetching, storing, and retrieving artifacts are domain/retrieval
concerns, not runtime stages.

LangGraph or another workflow runtime is not a first-version requirement. Add
one only after a demonstrated need for durable pause/resume, human approval,
long-running state machines, or reusable checkpointing.

## Model protocol

The model-facing protocol is provider-neutral:

- ModelRequest and ModelResponse
- AssistantMessage and FinalMessage
- ToolCall and ToolResultMessage

It supports native tool calls, multiple turns of result feedback, supported
parallel calls, text streaming, cancellation, and provider-specific message
conversion at the adapter edge. Structured JSON generation may remain useful
for isolated tasks but is not the primary planning mechanism.

`build_vnext_runtime()` composes the provider-neutral model client with the
vNext tool registry from `apps/api/app/vnext/.env`. It uses the shared
`DOTAMIND_LLM_*` names already used by the application; the local configuration
file is never a repository artifact.

## Tool runtime

A tool definition has a name, description, input model, output model, and
handler, with optional generic metadata such as source, timeout, and read-only
status. The runtime validates tool inputs before dispatch and returns explicit
tool errors; it never silently substitutes another data source or workflow.

Tool descriptions state capability, input, output, and important data limits.
Tool responses are bounded views: a capability may return a summary, canonical
references, coverage, and artifact references instead of the complete
underlying data. Detailed data is obtained only when an independent retrieval
capability is available and the model chooses that it is useful. No tool
description may require a fixed sequence of calls.

## Domain and provider layers

Domain services own entity resolution, provider selection, cross-source
mapping, normalization, de-duplication, domain errors, and provenance. They
produce provider-neutral canonical references and domain objects.

PandaScore Game to Valve match ID cross-source resolution is an internal,
reusable domain capability. It is not a model-facing Tool; match detail and
future artifact workflows may reuse the same resolver.

Provider adapters own upstream transport, authentication, rate limits, retry
policy, provider-specific models, and conversion from provider responses. Raw
provider JSON stays below this boundary and is never exposed to the model.

Provider-private resource IDs also stay below the artifact boundary. Canonical
Dota/Valve-native identifiers may cross it when they express domain identity:
for example, Valve match or team IDs, Steam account IDs, and hero, item, or
ability IDs are allowed; PandaScore resource IDs are not.

For example, MatchService can combine a PandaScore fixture, a resolved Valve
match identity, OpenDota detail, and Valve catalog enrichment. The model sees a
stable match or game summary with provenance, coverage, and references, not
provider-private IDs, raw payloads, or intermediate wiring.

## Artifact Construction Pipeline

Commit 3 establishes the implemented construction boundary:

    Provider Data
      -> Provider Adapter
      -> Domain References and Construction Context
      -> Resolvers
      -> Artifact Builder
      -> Canonical Artifact

The provider adapter maps provider fields, nulls, and source structure into
construction input. It does not catalog-resolve, construct an artifact, or
access the Artifact Store. Construction references are provider-neutral native
Dota identities such as Valve hero, item, and team IDs and Steam account IDs;
provider-private IDs remain below this boundary.

Resolvers enrich native references from an injected static Dota catalog
dependency without introducing a Catalog Entity framework. A catalog miss
preserves the native ID and produces `name = null`. The Artifact Builder alone
composes `GameSummaryArtifact`; provider adapters and resolvers may not.

Provider-native lookup keys may cross the adapter boundary as construction facts
when they are required for later canonical identity resolution. For example,
OpenDota `purchase_log.key` is preserved as `item_key` in construction input.
The provider adapter does not resolve it against the Item Catalog. Item identity
resolution happens at the Resolver/Builder boundary. Source representation is
not canonical identity.

This pipeline ends at artifact construction. It does not imply storage,
retrieval, tool, or runtime integration.

## Artifact Production Lifecycle

Commit 3.5 is the implemented application-level production boundary:

    Canonical Game Identity
      -> Provider Fetch
      -> Artifact Construction Pipeline
      -> Canonical Artifact
      -> ArtifactStore.put
      -> ArtifactRef

This layer coordinates already-defined provider, construction, resolver,
builder, and store boundaries. It owns the deterministic application work
required to produce and persist an artifact from canonical game identity. It
does not redefine provider normalization or artifact schema semantics.

Commit 3.5 does not add a model-facing artifact tool and does not make Agent
Runtime responsible for artifact creation, storage, refresh, expiration, or
reuse policy. Runtime may eventually dispatch capabilities that reach this
application boundary, but artifact production remains outside the runtime
itself.

Commit 3.5 freezes these production contracts:

- The typed OpenDota construction fetch validates that the response match ID is
  present and equals the requested canonical match ID.
- `ArtifactRef` identity is derived from the completed canonical artifact.
- Each `produce()` call fetches, constructs, and stores again; Commit 3.5 does
  not define cache, TTL, refresh, or freshness policy.
- `fetched_at`, provenance, and coverage are not persisted in the artifact
  store in this commit.

## Artifact Retrieval Capability

Commit 4 implements the retrieval boundary over stored artifacts:

    ArtifactRef / Lookup Criteria
      -> Retrieval Layer
      -> Bounded Artifact View

Retrieval answers what artifact data is available and returns bounded views
with explicit reference validity, coverage, and missing-data semantics. It does
not fetch provider data or construct a new artifact as part of the read path.
Production and retrieval are separate responsibilities even when a later
application capability may choose between reuse and production.

The model-facing retrieval capabilities are `artifact.search` and
`artifact.read`. They expose only the retrieval contract; the model is not
required to follow a fixed search-then-read workflow.

Commit 4 freezes these retrieval and integration contracts:

- A resolved game returned by `matches.get_detail` includes its canonical
  `valve_match_id`. The application handler produces and stores every resolved
  game artifact before the tool succeeds; unresolved or fixture-only games do
  not trigger production, and a production failure fails the whole tool.
- `artifact.search` accepts at most 100 canonical Valve match IDs, deduplicates
  them in first-seen order, checks only `ArtifactStore.exists`, and never reads,
  fetches, or produces an artifact.
- `artifact.read` accepts an exact `ArtifactRef`, returns either a top-level
  outline or a serialized bounded structural path, and only paginates when the
  final value is a list. It does not discover or produce artifacts.
- Structural paths support object fields and non-negative list indexes only;
  invalid paths use one `ArtifactPathNotFoundError` boundary.

## Artifact and Retrieval Layer

Phase 2.x therefore separates the data lifecycle into deliberate stages:

    Provider data
      -> Normalization / Construction
      -> Canonical Artifact
      -> Artifact Store
      -> Bounded Retrieval
      -> Model-facing Capability

Provider data is translated by domain normalization into canonical artifacts.
An artifact is reusable, normalized domain data with canonical references,
normalized values, provenance, coverage, completeness, and known missing
sections. It is not a raw provider-response cache. The Artifact Store is a
storage boundary outside model context; Commit 3.5 connects artifact production
to that boundary without assigning lifecycle ownership to Agent Runtime.

Commit 4 retrieval exposes independent, bounded views of stored artifacts. The
retrieval boundary enforces reference validity, path and size limits where
applicable, and explicit unavailable sections. It does not expose
provider-private IDs or raw payloads.

This diagram describes ownership and a possible data path, not a mandatory
request workflow. An existing artifact may be reused, a bounded domain summary
may be sufficient, and unavailable data must remain unavailable. The model
decides whether more detail is useful. Agent Runtime transports messages and
dispatches tools; it does not create, store, refresh, expire, or otherwise own
the artifact lifecycle.

## Context Boundary

Artifacts live outside model context. The model does not receive these by
default:

- raw provider payloads
- a full match dump
- large domain records or an entire artifact

Normal model-facing views contain only bounded information such as:

- canonical entity or artifact references
- concise match or game summaries
- available coverage and explicit missing sections
- bounded retrieval results when the model chooses more detail
- source, freshness, and uncertainty information where relevant

The retrieval layer enforces bounds and availability while the model chooses
when retrieval is useful. Artifact storage is never a responsibility of Agent
Runtime, and artifact retrieval is not a fixed workflow or mandatory sequence
of calls.

## Sessions and persistence

The initial conversation model is a persistent session transcript with bounded
history trimming and an AgentRun record. PostgreSQL is the likely durable store.
Redis is optional and must be justified by a concrete distributed coordination,
event replay, or throughput need rather than copied from Legacy V3.

Conversation reuse may carry canonical references across turns, but artifact
storage and retrieval remain separate contracts from runtime message history.

## Reliability and provenance

Every tool result carries its source or sources, fetch time when available,
warnings, and an optional confidence or identity status. A cross-source
inference is never presented as a native provider field. Artifact views also
preserve coverage, completeness, and known missing data.

The runtime exposes stable failure states for invalid inputs, unresolved
identity, provider errors, timeouts, cancellation, and exhausted general
budgets. It does not mask a failed tool as a successful answer.

## Rejected designs

- ExecutionPlan and reference-path planning DSLs
- Model-authored evidence obligations and EvidenceGraph contracts
- Intent or scenario routers that choose a fixed workflow
- Provider-level tools and provider-ID reasoning by the model
- Workflow instructions embedded in prompts or tool descriptions
- A separate prompt program for each match, tournament, or player scenario
- Separate scenario tools for every artifact section such as inventory,
  economy, or skill history
- Treating `artifact.search` or `artifact.read` as a mandatory multi-step
  workflow
