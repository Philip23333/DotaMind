# Architecture

DotaMind uses one agentic backend path. The deleted fixed report pipeline has
no compatibility fallback.

## Backend Layout

```text
app/
  api/v1/          /plan, /plan/stream and chat session routes, schemas, mapper
  application/     PlanService, chat repository and lease-aware SessionStore
  persistence/     async SQLAlchemy engine, PostgreSQL models and migrations
  agentic/
    graph.py       conditional LangGraph workflow
    state.py       AgentRunState and public-result state
    runtime/       Run/Attempt/Budget models, clocks, summaries, stream events and flat-state reset
    conversation/  compact Turn memory, summary extraction, history rendering
    planning/      ControllerDecision, Controller, contracts, sample policy
    prompts/       Controller prompt bundle, feedback renderers and audit versions
    nodes/         controller, decision validation, conversation/tool paths
    tools/         registry, executor, OpenDota, STRATZ, patch and local tools
    evidence/      EvidenceGraph and extraction helpers
    answer/        evidence-grounded answer synthesis
    critic/        rule-first evidence quality review
  integrations/    upstream API clients and deterministic helpers
  config/          policy.yaml business policy
  resources/       /debug/plan asset
```

## Valve Static Catalog

V3.3-3 adds one committed, versioned static catalog under
`apps/api/app/data/catalog/`: manifest, hero, ability and item runtime files plus
the developer-only `sync_audit.json`. `scripts/sync_game_data.py` is the only
networked maintenance path. It reads Valve Datafeed in English and Simplified
Chinese, normalizes and validates the complete bundle, then atomically replaces
the five reviewed files. Request-time code never calls Datafeed and has no
third-party or legacy constants fallback.

`DotaCatalogRepository` loads the manifest and three runtime entity files once,
validates IDs, references, tokens and manifest counts, and serves immutable-copy
lookups. The audit file is deliberately outside runtime resolution: reviewed
`legacy_or_unclassified` entities retain raw official text and unresolved tokens
for developers but are absent from resolver, tool evidence and Answer output.

The default ToolRegistry has exactly one `resolve_hero`, registered by
`dota_catalog_tools.py` with `official_snapshot` provenance. Chinese official
names and the reviewed `hero_aliases_zh.yaml` overlay are indexed together, so
aliases such as `火女` resolve exactly to Lina/25. Downstream STRATZ contracts
continue to reference `data.hero.hero_id`, while OpenDota registrations remain
unchanged; STRATZ also reads its English hero display-name index from the same Catalog repository. The former `hero_tools.py`
resolver and `data/heroes/dota2_heroes.yaml` snapshot were deleted rather than
kept as a parallel source.

## Controller and Graph

Every request first produces one discriminated `ControllerDecision`:

```text
direct_answer | clarification | context_missing | capability_boundary | tool_plan
```

Only `tool_plan` owns an `ExecutionPlan` and enters the external-data path:

```text
START
  -> run_init_node
  -> controller_node
  -> decision_validate_node
      -> direct_answer -> conversation_answer_node -> attempt_finalize_node
      -> clarification -----------------------------> attempt_finalize_node
      -> context_missing ---------------------------> attempt_finalize_node
      -> capability_boundary -----------------------> attempt_finalize_node
      -> tool_plan
           -> validate_plan_node
           -> tool_executor_node
           -> evidence_node
           -> answer_node
           -> critic_node
           -> attempt_finalize_node
  -> recovery_node
      -> terminal -> run_finalize_node -> response_node -> END
      -> replan   -> attempt_reset_node -> controller_node
```

Non-tool decisions never create an `EvidenceGraph` and never run the critic.
`intent` is only a semantic label. Graph routing reads `decision.kind` and
runtime status; it never branches on `intent`.

V3.2-3 has one request-level `RunContext`, one cumulative `RunBudget`, and one
or two sanitized `AttemptRecord` values. Attempt working fields remain flat on
`AgentRunState`; `reset_attempt_working_state()` is the sole reset mechanism
for the bounded recovery edge. The audit record contains only plan/tool/evidence/
answer/critic summaries, never complete plans, tool payloads, answer text,
critic reasons, history, controller raw output, or raw exceptions.

Tool execution has a private dispatch side channel. Registry lookup and input
validation occur before handler entry and do not consume tool budget. A
synchronous guard checks monotonic deadline and remaining tool budget after
pre-dispatch validation, then a callback records budget immediately before the handler, so
both successful and failed handler entries count exactly once. Dispatch stage
and stable internal error codes never modify the public `ToolResult`. Within a
Run, canonical fingerprints reuse same-id results and reject an equivalent call
under a changed id.

## Conversation Memory

Session memory remains a compact `Turn` history. It does not store raw model
messages and does not use a LangGraph checkpointer. Direct recall can read only
the current request's `state.history` snapshot through a validated
`ConversationBasis`:

- `query` recalls what the user asked.
- `resolved_entities` recalls successful hero/team/player resolution.
- `response_summary` recalls an earlier answer explicitly as a past answer.

`conversation_answer_node` renders these modes with deterministic templates.
Social, clarification and capability-boundary text may be generated by the
Controller. A `session_id` is a bearer capability for one user security
subject; cross-session history access is not available to the Controller.

## Stateful Request Idempotency (legacy boundary)

The public `/plan` and `/plan/stream` contracts are stateless debug contracts:
`PlanRequest` accepts only `query` and `game`. The V3.2 SessionStore/idempotency
components remain as isolated coordination and compatibility modules, but no
public chat request enters their old request-in-process Graph path.

## Redis Session Store

V3.2-5 adds `RedisSessionStore` behind the same `SessionStore` interface. It uses hashed
session/request identifiers, schema-v1 JSON envelopes, a per-session Redis lease and fencing
counter, plus atomic Lua operations for Turn append and RequestRecord completion. The API
lifespan selects `memory` or `redis` through configuration; Redis startup and runtime failures
surface as `session_store_error` and never fall back to a new in-memory session. API/worker
rebuilds recover state by reconnecting to the same Redis data. Redis Server restart durability is
a deployment concern: AOF/RDB and persistent volumes determine the allowed data-loss window.

## PostgreSQL Chat Persistence and Anonymous Multi-Chat

V3.3-1 adds `PostgresChatRepository` and the `chat_sessions` / `chat_turns` tables. A
browser creates one UUID v4 in localStorage and sends it as `X-DotaMind-Browser-Id`;
PostgreSQL stores only its SHA-256 hash. Session ownership is checked on every list,
transcript, rename, delete and stateful plan operation.

PostgreSQL is authoritative for complete transcript rows, compact `Turn` memory, pin state,
Run state and the strictly increasing fencing token. The Redis `SessionStore` supplies only
the short-lived lease/coordinator metadata. `ChatRunExecutor` acquires that lease, allocates
the PostgreSQL fencing token, loads history, injects the preallocated `run_id`, executes the
Graph, and atomically commits the public response plus compact Turn through
`PostgresChatRunRepository.complete_with_turn()`. A Redis flush, expiry or restart cannot
make a committed Turn regress; Redis is used for replayable Run events and cancel notices.

Deletion follows the same coordinator lock: it never deletes another owner's lock key,
deletes PostgreSQL first, clears only Redis data keys while the lock is held, and lets normal
transaction exit release the lock. A coordinator cleanup failure is logged but does not turn
an already committed PostgreSQL deletion into a false failure.

`apps/chat` lists and manages multiple local-browser sessions through assistant-ui's
`RemoteThreadListRuntime`; one assistant-ui thread maps to one DotaMind `session_id`. Each
started thread owns a long-lived `LocalRuntime`, while `ThreadHistoryAdapter` loads PostgreSQL
transcript and resumes an active Run from the Redis event stream. Run ID, phase, tool state and
terminal display data live in assistant message metadata; there is no second browser-level Run
Store. Login, cross-device sync, attachments, search, message branching and LangGraph
checkpointing remain outside this phase.

## Tool Plan Validation Order

For every Controller candidate:

```text
parse ControllerDecision
  -> apply_sample_policy(plan) once for tool_plan
  -> resolve effective required evidence
  -> validate ControllerDecision
  -> validate final ExecutionPlan
```

## Prompt Registry

`AgentController` closes `ToolRegistry` registration before rendering and caching its
Prompt bundle; existing ToolDefinition mappings are not copied or deeply frozen. The
default PlanService path registers and validates tools, then constructs the Controller and
GraphRunner with that registry. `controller_node` copies the bundle manifest to
`RunContext.prompt_versions` before the LLM call. Its SHA-256 identifies the configured/
prepared system prompt, not delivery or model success. Dynamic history and user-message
rendering are versioned without hashing request content. Prompt text, retry feedback,
validation errors and raw model output stay out of public and persistent DTOs.
`controller.recovery_rules=v1` versions the separate dynamic Recovery renderer;
it does not change the system Prompt hash.

Graph validation repeats deterministic checks but never mutates tool args,
metadata, or evidence obligations. Therefore state, debug output and execution
all use the same final plan.

## Tool and Evidence Contracts

`ToolDefinition` is the source of truth for:

- `input_model`: argument schema.
- `arg_contracts`: semantics and accepted plan-local references.
- `output_paths`: stable `$<call_id>.<output_path>` references.
- `source`: evidence provenance.
- `evidence_extractor` / `evidence_kinds`: possible extracted evidence.
- `mandatory_evidence`: runtime-owned primary proof obligations.

Evidence obligations are computed without mutating `plan.required_evidence`:

```text
contract.required_evidence
  union plan.required_evidence
  -> global kind obligations

each selected tool call's mandatory_evidence
  -> per-tool_call_id obligations
```

State exposes the original model list, effective kind union and stable source map as
`planner_required_evidence`, `effective_required_evidence`, and
`required_evidence_sources`. It also carries `mandatory_evidence_by_call`
internally. EvidenceGraph checks contract/model evidence globally by kind, but
checks registry mandatory evidence against the evidence emitted by each
successful `tool_call_id`; one call cannot satisfy another call's obligation.
Registry metadata is validated once at service startup; plan-specific
producibility is validated for each tool plan.

The first release mandates primary result evidence only. `sample_size` remains
available through sample-policy parameters, extraction, data-quality metadata,
answer disclosure and explicit contract/model requirements, but is not a
universal registry obligation.

## Terminal Result Priority

`attempt_finalize_node` calls the pure `resolve_terminal_outcome()` function to
seal each Attempt. `run_finalize_node` reuses the resolver for the final public
state and Run totals. The ordering is:

1. Controller transport/model error: `error/planning_error`.
2. Decision or plan validation error: `error/decision_validation_error`.
3. Tool failure: `error/tool_error`.
4. Answer model failure: `error/answer_error`.
5. Runtime budget/duplicate/deadline failure: `execution_budget_error` or
   `execution_timeout`.
6. Replan budget exhaustion: `insufficient_evidence/replan_exhausted`.
7. Missing effective evidence: `insufficient_evidence`.
8. Critic evidence-quality failure: `insufficient_evidence` without Recovery.
9. Otherwise the decision/contract succeeds.

In particular, a tool failure is never hidden as missing evidence, and an
answer failure is never hidden as a critic failure. Reference-resolution
failures produce failed `ToolResult` records and map to `tool_error`; otherwise
an unclassified runtime error falls back to `execution_error`. Terminal errors
also replace the Controller's provisional `decision accepted` reason with a
stable failure reason.

`response_node` only accepts a finalized state with one or two contiguous Attempts,
applies the safe-failure
allowlist, and serializes the response. It does not contain a legacy terminal
reduction path. Missing-evidence Recovery can produce Attempt 1 once; unhandled
exceptions, cancellation, and process exit are deferred to V3.2-6.

Wall-clock UTC timestamps provide audit fields such as `deadline_at`; all
durations and timeout observation use an injectable monotonic clock. V3.2-3
blocks not-yet-started business nodes and handlers after deadline while allowing
attempt/recovery/run/response closure.

## Chat Frontend

`apps/chat` is a Next.js and assistant-ui client for the Chat Run API. Sending creates a
durable Run with a client request UUID and subscribes to
`/api/v1/chat/runs/{run_id}/events`. The subscription replays from `after=0` on recovery;
disconnecting the observer never cancels the detached Run. The explicit DotaMind Stop Action
calls the cancel endpoint, while navigation or subscription abort only closes observation.
phase/tool/delta/result/status events map into the assistant-ui runtime and terminal results
update transcript/title metadata.

The chat renders those events as one compact per-message run card: analysis,
tool use, answer organization and evidence review. It is expanded while running,
folds after a successful final result, and stays open on failure or cancellation.
Provisional prose is explicitly marked as pending review and is discarded when
the stream terminates in error or the final status is not `ok`. The frontend does
not introduce another model endpoint, a fallback runtime or a legacy
compatibility route. `/plan` and `/plan/stream` remain stateless debug surfaces only;
durable thread listing/history, heartbeat and Run recovery are provided by the Chat Run
Repository/Event Bus boundary.

## Debugging

Use `http://localhost:8001/debug/plan`. It shows the Run, budget, one or two
Attempts, Controller decision, final plan, required-evidence sources, tools,
EvidenceGraph, answer, critic and timed trace.
The legacy frontend remains deleted; `apps/chat` is the new V3.3 client for the
single agentic API path, not a restored compatibility frontend.
