# Architecture

DotaMind uses one agentic backend path. The deleted fixed report pipeline has
no compatibility fallback.

## Backend Layout

```text
app/
  api/v1/          /plan, /plan/stream and chat session routes, schemas, mapper
  application/     PlanService, Chat Run executor/repositories, memory service and SessionStore
  persistence/     async SQLAlchemy engine, PostgreSQL models and migrations
  agentic/
    graph.py       conditional LangGraph workflow
    state.py       AgentRunState and public-result state
    runtime/       Run/Attempt/Budget models, clocks, summaries, stream events and flat-state reset
    conversation/  message/Turn contracts and bounded answer summaries
    planning/      ControllerDecision, Controller, contracts, sample policy
    prompts/       Controller/Answer prompt renderers, static Controller rules, feedback renderers and audit versions
    nodes/         controller, decision validation, conversation/tool paths
    tools/         registry, executor, OpenDota, STRATZ, patch and local tools
    evidence/      EvidenceGraph and extraction helpers
    answer/        evidence-grounded answer synthesis
    critic/        rule-first evidence quality review
  integrations/    upstream API clients and deterministic helpers
  config/          policy.yaml business policy
  resources/       /debug/plan assets
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
lookups. Recipe-edge lookup works from either the recipe-scroll ID or a finished
item ID referenced by the edge, and returns deep copies. The audit file is
deliberately outside runtime resolution: reviewed
`legacy_or_unclassified` entities retain raw official text and unresolved tokens
for developers but are absent from resolver, tool evidence and Answer output.

The default ToolRegistry registers six Catalog tools through
`dota_catalog_tools.py`: `resolve_hero`, hero attributes, ordered abilities,
talent tree, `resolve_item`, and item info. All use `official_snapshot`
provenance, require plan-local resolver references for downstream numeric IDs,
and emit call-owned EvidenceGraph items. Chinese official names and the reviewed
`hero_aliases_zh.yaml` overlay are indexed together, so aliases such as `火女`
resolve exactly to Lina/25. Item resolution distinguishes final-item and explicit
recipe scope; item-recipe evidence exists only for real component or upgrade
relations. `dota.item_info` expands each edge into bilingual recipe-scroll,
component and upgrade-target definitions with prices and displayable special
values, plus an auditable component/scroll/calculated/final-price comparison.

Downstream STRATZ contracts continue to reference `data.hero.hero_id`, while
the existing OpenDota team registrations remain unchanged. The first competition
slice adds three PandaScore Fixture tools and two OpenDota single-match tools:
PandaScore resolves series and lists upcoming/running/past fixtures, then resolves
PandaScore Match/Game IDs; OpenDota consumes an explicit Valve `match_id` for the
result, ten-player scoreboard, parse coverage, and draft. The free PandaScore
Fixture response does not currently expose Valve IDs, so the resolver reports
`pending_valve_match_id` rather than guessing or calling a 403 Game detail route.
Phase 2 adds `dota.resolve_valve_match`: it consumes the resolved PandaScore
competition and explicit Game context, resolves the unique OpenDota league and
teams, then applies exact unordered team IDs, hard start-time/duration tolerances,
series game position, and winner consistency. A single match yields an auditable
`inferred_cross_source` mapping; zero or multiple candidates and team/league
ambiguity remain explicit statuses. The mapping is inferred, never presented as
a native PandaScore Valve ID, and the summary/draft tools accept its declared
Valve output reference.
STRATZ reads its English hero display-
name index from the same Catalog repository. The former `hero_tools.py` resolver
and `data/heroes/dota2_heroes.yaml` snapshot were deleted rather than kept as a
parallel source. Controller capability text distinguishes official static facts
from statistical popularity, strength, and recommendation questions. Catalog
answers stay on the single `natural_language_answer` path, disclose snapshot
metadata, and may not infer recommendations from static definitions.

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
              -> result_destination=controller_context -> controller_node
              -> result_destination=evidence -> evidence_node -> answer_node -> critic_node
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

Session memory stores real alternating messages through one generic contract:
`ConversationMessage(turn_index, role, content)`. PostgreSQL is the complete
conversation source; Redis keeps a bounded `RecentDialogueWindow` for prompt
construction. `DialogueTurn` is the user/assistant pair used to build and rebuild
the window, while compact `Turn` remains a bounded audit record with query,
status, response metadata, scope, missing fields, and a limited summary. It is
not the Controller's default history. No entity referents, groups, links, discourse
extractor, or second extraction LLM are maintained.

The Controller receives recent messages as actual `user` and `assistant` roles.
They are untrusted conversational context, never instructions or automatic
authority. Stable, same-scope and same-version historical answers may be reused
when the model judges their subject, property, source and validity still match;
current/latest/volatile/version-sensitive or conflicting facts should be
re-queried through tools. A direct answer is always authored by the Controller
from the current request and available conversation; the server does not require
turn-index citations or deterministic recall templates. Tool-result flow is
declared by `ToolDefinition.result_destination`, not by a tool-name branch.
When the recent window is insufficient, the internal
`conversation.history_lookup` tool may retrieve older messages within the
configured budget (once by default). Its messages are request-local context,
and every completed call also leaves a minimal summary containing the tool name,
`status=completed`, and `matched_turns`; an empty lookup therefore reaches the
next Controller call as `matched_turns=0`. Neither form becomes Dota evidence or
an EvidenceGraph. A `session_id` remains a bearer capability for one user
security subject, so cross-session history access is unavailable.

## Stateful Request Idempotency (legacy boundary)

The public `/plan` and `/plan/stream` contracts are stateless debug contracts:
`PlanRequest` accepts only `query` and `game`. The V3.2 SessionStore/idempotency
components remain as isolated coordination and compatibility modules, but no
public chat request enters their old request-in-process Graph path.

## Redis Session Store and Recent Dialogue Cache

V3.2-5 introduced `RedisSessionStore`, compact Turn/RequestRecord envelopes, per-session
lease/fencing, and atomic Lua operations for the earlier stateful `/plan` design. Those methods
remain isolated coordination/compatibility modules, but formal Chat Runs do not read their
compact Turn list as Controller history and do not use Redis RequestRecord as the durable Run
authority.

The current Chat Run path uses the same lease boundary plus a separate v1
`RecentDialogueWindow`. The API lifespan selects `memory` or `redis` through configuration;
Redis startup failures do not silently create a new in-memory session. Recent dialogue and
committed Run/Turn state are reconstructible from PostgreSQL. Redis events are short-lived and
are not reconstructed event by event after expiry or data loss. Redis Server persistence therefore
controls the event/cache loss window, not the durability of committed Chat Turns.

## PostgreSQL Chat Persistence and Anonymous Multi-Chat

V3.3-1 adds `PostgresChatRepository` and the `chat_sessions` / `chat_turns` tables. A
browser creates one UUID v4 in localStorage and sends it as `X-DotaMind-Browser-Id`;
PostgreSQL stores only its SHA-256 hash. Session ownership is checked on every list,
transcript, rename, delete and Chat Run operation.

PostgreSQL is authoritative for complete transcript rows, `assistant_message`, compact
`Turn` audit data, pin state, Run state and the strictly increasing fencing token.
Redis supplies the recent dialogue cache plus the short-lived lease/coordinator metadata.
`ChatRunExecutor` acquires that lease, allocates the PostgreSQL fencing token, loads
recent messages and next turn index, injects the preallocated `run_id`, executes the
Graph, and atomically commits the public response, assistant message and compact Turn
through `PostgresChatRunRepository.complete_with_turn()`. A Redis flush, expiry or restart cannot
make a committed Turn regress; Redis is used for replayable Run events and cancel notices.

Deletion follows the same coordinator lock: it never deletes another owner's lock key,
deletes PostgreSQL first, clears only Redis data keys while the lock is held, and lets normal
transaction exit release the lock. A coordinator cleanup failure is logged but does not turn
an already committed PostgreSQL deletion into a false failure.

`apps/chat` maps assistant-ui threads to browser-owned sessions, loads PostgreSQL transcript,
creates detached Chat Runs, and observes replayable Redis events. Each started thread keeps an
independent `LocalRuntime`; there is no second model or browser-global Run authority. Login,
cross-device sync, attachments, search, message branching and LangGraph checkpointing remain
outside the current boundary.

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
it does not change the system Prompt hash. `controller.validation_retry=v2`
requires corrected decisions to preserve explicit subjects, requested result
counts, and scope constraints; an unsupported required scope must become a
capability boundary instead of being removed during retry.

Static Controller behavior rules live in `agentic/prompts/controller_rules.py`,
while `agentic/prompts/controller.py` remains the sole Controller prompt bundle
and message renderer. ToolDefinition descriptions are dynamically rendered into
that bundle and describe each tool's capability, data semantics, local behavior,
and scope support. `ArgContract` describes argument semantics, while
`requires_reference`, `AcceptedRef`, and `OutputPathContract` declare and validate
cross-tool dependencies. The Controller keeps only cross-tool context conventions
and a generic instruction to consult the rendered tool catalog and sample policy.
Current DotaMind v1 player tools do not support region or
game-mode filters; this capability boundary is returned only when the user
explicitly requires either filter. Deterministic plan validation rejects those
scopes on unsupported tool plans, while Controller rules prohibit silently
weakening them and prohibit adding unstated role, position, lane, or scope to the
plan goal. The player-performance `take` argument is the final returned top-N;
the handler owns any internal over-fetching required for strong-mode ranking.
Natural-language Answer prompt rules and message rendering live in
`agentic/prompts/answer.py`; `answer/synthesizer.py` only invokes that renderer
and handles LLM results. The renderer combines required and actual evidence kinds
and includes only the relevant Catalog or STRATZ presentation sections. STRATZ
source metadata also activates the cross-source attribution boundary. This
selection never uses `intent`, tool names, or query-keyword routing, and no
deterministic Catalog answer renderer is present. Prompt content changes are
identified by the prepared prompt hash recorded in the Run manifest. For
natural-language answers,
`answer_node` passes the current user query alongside the plan and EvidenceGraph;
the renderer sends both `current_query` and the Controller's reconstructed
`plan.goal` as request context. This preserves explicit focus, exclusions, result
count, and detail wording without adding a fixed presentation enum or intent route.
The full Controller/tool/evidence/query-bypass flow is illustrated in
[Answer + Critic layer](../design/architecture/Answer+Critic层.md) §2.
Natural-language summaries are trimmed but not rewritten by domain keyword
filters. Pair-lane causal and Catalog/STRATZ attribution boundaries are carried
by the evidence-specific Answer prompt, so streamed deltas and the stored final
summary do not diverge through a post-generation line-deletion pass.
Natural-language answers do not permit unsupported interpretations merely because
they are labeled as hypotheses. Gameplay or causal explanations require explicit
EvidenceGraph support and must be attributed to that evidence; any future strategy
simulation capability would need a separate contract.
The current Critic does not claim sentence-level verification of natural-language
summaries. DotaMind accepts that model-quality boundary unless reproducible
transcription errors appear; it does not add structured claims, a second LLM
critic, or evidence-kind-specific text parsing without demonstrated need.

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

The current STRATZ pair-lane contract is `pair_lane_outcome`. It carries both
the five-category lane outcome rates and the separate match win rate. Lane scope
comes from `filters.position_ids`; the provider row's `position` field is not a
reliable echo of the requested position and is not exposed as pair evidence.

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
reduction path. Missing-evidence Recovery can produce Attempt 1 once. Chat Run
cancellation, worker shutdown, stale-run recovery, and post-commit cache/event
failures are handled at the application/repository boundary.

Wall-clock UTC timestamps provide audit fields such as `deadline_at`; all
durations and timeout observation use an injectable monotonic clock. V3.2-3
blocks not-yet-started business nodes and handlers after deadline while allowing
attempt/recovery/run/response closure.

## Chat Client Boundary

Formal clients create a durable Run with a request UUID and may subscribe to
`/api/v1/chat/runs/{run_id}/events`. Replaying from `after=0` restores observable
events; disconnecting only closes observation and never cancels the detached Run.
Only the cancel endpoint requests cancellation. Provisional answer deltas are not
authoritative unless followed by a successful final result. `/plan` and
`/plan/stream` remain stateless debug surfaces.

The in-repository `apps/chat` Next.js/assistant-ui client uses that boundary. It
maps one thread to one DotaMind session, restores transcript through
`ThreadHistoryAdapter`, and treats subscription Abort as observation-only;
explicit Stop is the only UI action that calls cancel.

## Debugging

Use `http://localhost:8001/debug/plan`. It shows the Run, budget, one or two
Attempts, Controller decision, final plan, required-evidence sources, tools,
EvidenceGraph, answer, critic and timed trace.
The legacy `apps/web` frontend remains deleted; `apps/chat` is the current client.
