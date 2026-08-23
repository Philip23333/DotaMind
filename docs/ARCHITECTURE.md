# Architecture

## Status

This is the vNext target architecture. The checked-out Legacy code does not
claim to implement it until each replacement is deliberately delivered.

## Principles

- The model owns ordinary business reasoning: it decides what information is
  needed, which domain tools to call, whether to continue, and when to answer.
- Runtime code owns durable boundaries: schemas, authorization, identity,
  transport, normalization, budgets, cancellation, and persistence.
- Tools expose Dota domain capabilities, never provider plumbing or a complete
  scenario workflow.
- Domain services hide provider selection, identifier conversion, cross-source
  resolution, and data composition.
- Scenarios are evaluated as behavior, not encoded as runtime routes.

## System boundary

    User
      -> Chat / API
      -> Agent Runtime
      -> LLM <-> Dota Agent Tools
                   -> Domain Services
                   -> Provider Adapters

The API owns authentication and request ownership. The runtime owns messages,
tool dispatch, general limits, trace events, and cancellation. It does not know
what a tournament, player build, or match-detail scenario is.

## Agent loop

The initial runtime is a thin native tool-calling loop:

    messages
      -> model response
      -> final answer, or tool calls
      -> validated parallel-safe tool execution
      -> tool-result messages
      -> model continuation

It enforces maximum steps, maximum tool calls, deadlines, cancellation, streaming,
and stable error reporting. It does not use an ExecutionPlan DSL, required-evidence
DSL, fixed result destinations, or scenario-specific replan protocol.

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
They do not instruct the model to follow a fixed sequence of calls.

## Domain and provider layers

Domain services own entity resolution, provider selection, cross-source mapping,
normalization, de-duplication, domain errors, and provenance. Provider adapters
own upstream transport and provider-specific models.

For example, MatchService can combine a PandaScore fixture, a resolved Valve
match identity, OpenDota detail, and Valve catalog enrichment. The model sees a
stable MatchDetail domain result, not provider IDs or intermediate wiring.

## Sessions and persistence

The initial conversation model is a persistent session transcript with bounded
history trimming and an AgentRun record. PostgreSQL is the likely durable store.
Redis is optional and must be justified by a concrete distributed coordination,
event replay, or throughput need rather than copied from Legacy V3.

## Reliability and provenance

Every tool result carries its source or sources, fetch time when available,
warnings, and an optional confidence or identity status. A cross-source inference
is never presented as a native provider field.

The runtime exposes stable failure states for invalid inputs, unresolved identity,
provider errors, timeouts, cancellation, and exhausted general budgets. It does
not mask a failed tool as a successful answer.

## Rejected designs

- ExecutionPlan and reference-path planning DSLs
- Model-authored evidence obligations and EvidenceGraph contracts
- Intent or scenario routers that choose a fixed workflow
- Provider-level tools and provider-ID reasoning by the model
- Workflow instructions embedded in prompts or tool descriptions
- A separate prompt program for each match, tournament, or player scenario
