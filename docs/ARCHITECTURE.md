# Architecture

## Status

This is the vNext target architecture. The checked-out Legacy code does not
claim to implement it until each replacement is deliberately delivered.
The artifact and retrieval boundaries below are target contracts; they do not
claim that a Phase 3 store or retrieval tool exists today.

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
bounded views. The proposed Artifact Store would retain normalized canonical
data that should not automatically enter model context. Provider Adapters own
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

## Domain, retrieval, and provider layers

Domain services own entity resolution, provider selection, cross-source
mapping, normalization, de-duplication, domain errors, and provenance. They
produce provider-neutral canonical references and domain objects.

Retrieval services own availability and access to canonical data. They can
report existing coverage, return bounded summaries or sections, and preserve
missing or unavailable data. They do not change entity identity merely because
a provider has partial data. Retrieval may use the Artifact Store and provider
adapters, but the model never reasons over provider IDs or provider schemas.

The proposed Artifact Store would define the future boundary for normalized
canonical artifacts. It would not be a raw provider-response cache and would
not be owned by Agent Runtime. Its backend may eventually be a cache or durable
store; that decision and implementation are separate from the runtime loop.

Provider adapters own upstream transport, authentication, rate limits, retry
policy, provider-specific models, and conversion from provider responses. Raw
provider JSON stays below this boundary and is never exposed to the model.

For example, MatchService can combine a PandaScore fixture, a resolved Valve
match identity, OpenDota detail, and Valve catalog enrichment. The model sees a
stable match or game summary with provenance, coverage, and references, not
provider IDs, raw payloads, or intermediate wiring.

## Artifact Architecture

An artifact is defined as canonical domain data that a future store may cache
or persist after assembly from normalized provider facts. It is intended to be
a reusable data object, not a provider response cache and not a scenario
workflow.

Examples include:

- Game Artifact
- Player Match Artifact
- Draft Artifact
- Timeline Artifact

The conceptual transformation is:

    Provider data
      -> domain normalization
      -> canonical artifact

The transformation describes data ownership and quality boundaries. It is not
a required A-to-B-to-C sequence for every user request. An existing artifact
may be reused, a bounded domain result may be sufficient, and unavailable data
must remain explicitly unavailable.

The artifact contract would carry quality metadata such as source, fetched
time, schema version, coverage, completeness, and missing sections. Canonical
artifact content would use domain references and normalized fields; provider
identifiers and raw provider JSON would remain implementation details below the
model boundary.

## Model Context Boundary

The model should not receive an entire match detail, an entire game timeline,
or raw provider JSON by default. A normal tool view contains only the bounded
information needed to decide what to do next, for example:

- entity or artifact references
- a concise identity and summary
- available coverage and explicit missing sections
- source and freshness information where relevant

If the question requires detail, the model may choose an available artifact
search or read capability with an explicit bounded query or section. The
retrieval layer enforces reference validity, limits, and availability; the
model chooses when retrieval is useful. The model never assumes storage
responsibility and never receives provider payloads as a substitute for a
domain contract.

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
- Treating artifact search or read as a mandatory multi-step workflow
