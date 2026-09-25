# Product Run State and Chat Transport

## Status and scope

This document defines the accepted target for the chat execution experience.
Phases 1-4 are design-approved, including Markdown-only rendering and continued
generation when switching threads. The product Run State schema, synchronous
projection, and deterministic projection tests are implemented. Runtime now
emits answer-stage and answer-attempt lifecycle events and publishes answer
deltas during the model invocation. The product projection is not connected to
Runtime or product chat; HTTP transport and frontend behavior remain pending.
The current product protocol does not represent attempt reset, so this Runtime
milestone does not establish browser fallback replacement. End-to-end acceptance
is not complete. Phases 5-6 are planned, not implemented.
Code remains the authority for current behavior. This document owns the product
Run State contract; `../ROADMAP.md` owns delivery order.

The first version exposes real execution activity, tool progress, and a final
answer streamed as it is generated, following the ChatGPT-style interaction
requested for this product. It keeps canonical answer text separate
from presentation metadata and makes generation, cancellation, and persistence
outcomes explicit.

Not included: raw model reasoning display,
model-generated progress summaries, resumable streams, cross-tab synchronization,
durable execution recovery, or a full trace viewer. Refresh restores saved
dialogue; it does not promise to reconnect to an in-flight run.

## Decisions and boundaries

**Decision:** Project structured Runtime events into a product-owned Run State,
then replicate that state through AssistantTransport.

**Reason:** Runtime already knows execution facts. The product needs a bounded
display projection, while a library can own stream encoding and client decoding.

**Not included:** assistant-ui imports, transport operations, panel visibility,
collapse state, or animation state inside AgentRuntime.

```text
AgentRuntime -> structured runtime events
             -> Product projection + persistence outcome
             -> product Run State
             -> AssistantTransport / assistant-stream
             -> state converter -> assistant-ui messages and process UI
```

- Runtime owns execution/answer stage boundaries, tool lifecycle, cancellation,
  and the canonical final answer or terminal execution error.
- Product owns request/message identity, safe activity projection, answer
  delivery, repository writes, and persistence errors.
- Transport owns state replication and command delivery. It does not define
  business completion, authorize sessions, or make writes idempotent.
- assistant-ui owns frontend thread/message interaction, scrolling, actions,
  and rendering integration. DotaMind supplies history adapters and conversion;
  its repository remains authoritative for saved dialogue.
- Presentation owns collapse/expand behavior and standard Markdown rendering.
  Catalog entity enhancement is deferred.

Only product-approved fields cross the transport boundary. Do not replicate
SessionExecutionHistory, model requests, raw reasoning, full tool observations,
or Runtime internal state. Client-supplied transport state is not authoritative
for history, authorization, tool configuration, or saved completion.

## State semantics

The lifecycle semantics below are approved. The following type illustrates them;
exact wire field names, activity/error shapes, and bounds remain implementation
details to specify before behavior changes. Prefer the smallest shape satisfying
these invariants.

```ts
type RunState = {
  requestId: string;
  assistantMessageId: string;
  status: "running" | "completed" | "failed" | "cancelled";
  stage: "execution" | "answer";
  activity: ActivityItem[];
  answer: {
    attemptId: string | null;
    kind: "primary" | "degraded" | "deterministic" | null;
    text: string;
    status: "pending" | "streaming" | "ready" | "interrupted";
  };
  persistence: "pending" | "saving" | "saved" | "failed";
  // Existing visual metadata may be retained; first-version UI does not use it.
  visualEntities?: CatalogVisualEntity[];
};
```

`status` describes the Runtime outcome. `stage` identifies its current or last
stage. `persistence` describes saving the canonical dialogue turn; pending means
no save has started and may remain so for a cancelled or failed run without an
answer. Request settlement must consider these separate dimensions: Runtime
completion alone does not mean persistence or the transport request has ended.

`tooling` is derived from active tool calls rather than a competing top-level
stage. Tools may alternate with model requests throughout execution. An ordered
activity list records those occurrences, with stable item identity and tool call
IDs for matching starts and terminal updates. The projection must have explicit
size/count bounds and disclose omitted activity rather than growing without
limit during long runs. It is not a replacement for the trace.

The product Run State describes one run. One accepted request corresponds to one
assistant message throughout execution, streaming, fallback, and persistence.
The transport converter combines saved thread messages and that active message;
fallback never creates a second assistant message. History reconciliation and
same-request save retries must preserve this mapping rather than duplicate a
turn. Answer attempts change independently of request/message identity.

### Required transitions and outcomes

| Event or outcome | Product meaning |
| --- | --- |
| Request accepted | Associate one request and assistant message; running/execution, answer pending |
| Tool started/completed/failed | Update that call's activity; a tool failure alone does not fail the run |
| Answer stage entered | Set stage to answer even before answer text exists |
| Answer text delta received | Append to the current answer attempt immediately; answer streaming, Runtime still running |
| Answer generation fails | Replace the failed attempt with fallback in the same message; do not preserve its text as the active answer |
| Canonical final produced | Answer ready, Runtime completed; begin saving |
| Save succeeds | Persistence saved; retain canonical message identity |
| Save fails | Keep ready answer and completed Runtime status; expose persistence failure separately |
| Runtime fails before final | Failed run with a safe execution error; no synthetic successful answer |
| User cancellation before final | Cancelled run; settle active process UI without declaring success |
| Connection ends without terminal confirmation | Stop the local busy state and report interruption; do not infer server success or failure |

If user cancellation or disconnection interrupts an answer already streaming,
retain its visible partial text and mark it interrupted. It
is not a canonical completed answer and is not saved as a successful dialogue
turn. An ordinary connection interruption must not overwrite an already
confirmed ready answer. Refresh still restores only saved dialogue.

User cancellation does not trigger fallback. Cancellation after canonical
generation or during saving must not erase the ready answer or undo a successful
write. The persisted repository result is authoritative if completion and
cancellation race; stopping the client cannot promise rollback. An unconfirmed
save must not be labeled saved, and history reload reconciles committed results.
A disconnected browser cannot rely on receiving a terminal event or fallback.

Preserve existing request-id idempotency and completed-answer caching: retrying
a save with the same request must not rerun the model or append a duplicate turn
while that cached answer remains available. Process restart recovery is outside
the first version; an in-memory cache is not a durable recovery guarantee.

### Approved fallback replacement policy

**Decision:** A generation error replaces the streamed answer with fallback in
the same assistant message, even when users have already seen partial text.

**Reason:** The requested interaction delivers a fallback answer directly rather
than leaving generation errors for the user to retry manually.

**Not included:** Fallback on user cancellation, database save failure, or a
client-side network interruption. A tool failure may be recoverable during
execution and does not by itself trigger answer replacement.

Use the existing bounded primary -> degraded -> deterministic fallback policy
and shared answer deadline. Do not add an unbounded retry loop or reset the
deadline. If the remaining budget cannot support another model call, use the
existing deterministic fallback path.

Every answer attempt has an identity and a kind. Before replacement text is
published, atomically select the new attempt, clear the old text, and mark the
answer pending. Subsequent fragments make it streaming. Deltas and canonical
completion must match the active attempt; stale updates cannot restore failed
text. Record the switch as process activity without adding error text to the
answer body. Failed attempts remain diagnostic evidence under the trace policy.

A model-generated degraded answer streams live. A deterministic fallback can
replace the text and become ready in one update. Never concatenate attempts or
append a full canonical answer to already-streamed text. Reconcile the accepted
final text once, then mark Runtime completed and begin saving. Successful
fallback is a completed delivery; its degraded origin remains distinguishable
from a primary answer. Only the accepted canonical answer is saved to dialogue.

If an infrastructure failure prevents even the fallback from being delivered,
report terminal failure/interruption rather than claiming a ready answer.
The fallback policy does not make a broken connection deliverable.

## Activity and final-answer presentation

First-version activity labels describe observable facts: processing a request,
querying a capability, a tool finishing/failing, or generating an answer.
`ModelRequested` does not prove that the model is confirming scope, comparing
strategies, or performing another specific reasoning step. Do not invent such
summaries. Tool details are bounded, product-safe projections, not full results.

The UI may group process activity, tool activity, and the final answer visually,
but must preserve the underlying occurrence order. Do not assume one reasoning
block followed by one tool block. Once the canonical final is ready, collapse
the process area by default; let the user reopen it. Saving/error indicators
remain visible independently. Do not repeatedly override manual expansion on
subsequent state updates.

Stream final-answer text as the model produces it in the first version. A short
pending indicator before the first fragment is allowed, but a persistent
"generating answer" placeholder followed by the whole answer does not satisfy
this requirement. Do not simulate streaming by replaying buffered completed text
with a frontend typing animation. Chunk boundaries need not match individual
tokens; fragments must reach the browser before the model call completes.

Changing wire format alone is insufficient: current model invocation code
buffers publishable deltas until the invocation returns. Phase 2 must remove
that buffering from the answer-delivery path while keeping execution text and
raw reasoning out of the final-answer channel. Final completion reconciles the
streamed text with the canonical final once, without appending it a second time.
Persistence starts only after canonical completion and must not gate live text.

## History and metadata

Durable dialogue contains user text, canonical final assistant text, and
presentation metadata. Execution activity is ephemeral; existing trace recording
may retain diagnostic process evidence under its own policy. Do not add raw
reasoning, tool logs, drafts, or fabricated answers to dialogue history.

This rule does not remove the Agent's SessionExecutionHistory or change context
compaction, effective-history retention, or follow-up behavior.

The backend already stores canonical final text and catalog visual entities
separately. Preserve existing stored metadata without requiring the frontend to
consume it. First-version live and historical answers share standard Markdown
rendering only. Remove catalog-mention text rewriting from the normal display
path; do not replace it with entity enhancement in this phase. Standard Markdown
images and links explicitly present in the answer remain renderable. Copying and
persistence use canonical text, with no injected icon/image Markdown.
After refresh, saved messages need not reconstruct an ephemeral process panel.

## Six implementation phases

### Phase 1: product state contract

Lifecycle design approved: three independent state dimensions, one message per
request, live answer streaming, generation-error fallback replacement, and
separate cancellation/network/persistence behavior. This is design acceptance,
not a claim that Runtime behavior is implemented.

The `ProductRunState` schema and synchronous `ProductRunStateProjector` are
implemented in `apps/api/app/vnext/product/run_state.py`, with deterministic
tests in `apps/api/tests/vnext/test_product_run_state.py`. This establishes the
product state projection only; Runtime events, product chat, transport, and
frontend remain unconnected, so the phase's end-to-end acceptance is pending.

The implemented product state defines request and assistant-message identity,
ordered bounded activity, independent run/stage/answer/persistence status, safe
errors, cancellation, and persistence retries. Its synchronous projector accepts
facts without doing I/O, choosing fallbacks, or saving. The remaining Phase 1
acceptance is to verify the shared backend/frontend transition contract and the
thread/message envelope at integration boundaries; those consumers are not part
of this implementation milestone.

Acceptance: backend and frontend share an unambiguous transition contract for
success, tool failure, fallback, cancellation, disconnection, and save failure.
Do not defer these semantics to Phase 6.

### Phase 2: Runtime events and product projection

Design approved. Runtime answer-stage and answer-attempt lifecycle events, plus
live answer delivery during model invocation, are implemented with deterministic
tests. Product projection integration and phase acceptance remain pending. This
phase changes Runtime event production and product projection, not the public
transport protocol or UI.

**Decision:** Publish answer fragments during the model invocation and expose
explicit answer-stage and answer-attempt boundaries. Keep one Runtime execution
flow and a separate product projection.

**Reason:** Consumers must observe text before generation finishes and distinguish
failed attempts from their replacements without guessing from text or tool counts.

**Not included:** UI state in Runtime, execution-text/reasoning passthrough,
AssistantTransport integration, or another background execution controller.

Reuse existing model/tool/terminal events, including AgentCancelled. Runtime
reports tool identity, call identity, and outcome; Product chooses bounded
display labels and ordered activity. Tool failure alone does not fail the run.

The Runtime emits `AnswerStageStarted`, `AnswerAttemptStarted`, and
`AnswerAttemptFailed`; `TextDelta` and `AgentCompleted` carry an optional
`attempt_id` for compatibility with hand-constructed events. Production answer
paths provide that identity, including deterministic answers and overflow
retries. Primary and degraded answer paths publish each streamed text fragment
through the Runtime event flow before the terminal model response. Execution and
compaction text remain trace-only. The product projector does not yet consume
these events.

| Event semantic | Runtime fact | Product projection |
| --- | --- | --- |
| Answer stage entered | Execution ends and answer preparation starts | Set stage to answer before the first model call or fragment |
| Answer attempt started | Select an attempt ID and primary/degraded/deterministic kind | Atomically select the attempt, clear prior text, and set answer pending |
| Answer text delta | A displayable fragment belongs to the active attempt | Append immediately and set answer streaming |
| Answer attempt failed | This attempt failed to produce an accepted final | Record failure activity; await replacement or terminal outcome |
| Agent completed | A canonical final was accepted for a specified attempt | Reconcile text once, set ready/completed, then enter product persistence |

Stage entry precedes answer-context preparation; attempt start identifies an
actual answer attempt. Deltas and final completion carry attempt identity. The
projection rejects stale-attempt updates. Cancellation and fatal failure retain
their existing terminal meanings; they must not be disguised as completion.

Runtime sequentially consumes an async model stream that yields fragments and
its terminal result, forwarding answer fragments immediately through the
existing Runtime event flow. The answer-delivery path does not buffer fragments
until invocation completion. No background queue/task/controller is introduced
to animate text. The terminal model response still owns protocol validation,
usage accounting, and complete-result confirmation; deltas are not proof of
successful completion. Stream cleanup, deadlines, trace recording, and
context-governance behavior remain in place. Execution text and raw reasoning
remain excluded from the final-answer channel. Complete-only model clients still
produce no synthetic text fragments.

Required replacement order:

```text
primary attempt started -> answer deltas -> primary attempt failed
  -> degraded attempt started (reset) -> answer deltas
  -> Agent completed with degraded canonical final

if degraded generation also fails:
degraded attempt failed -> deterministic attempt started (reset)
  -> Agent completed with deterministic canonical final
```

Use the existing bounded fallback policy and shared deadline; exhausted budget
may select deterministic fallback directly. User cancellation emits termination,
not a fallback attempt. No fragments or new attempts are published after terminal
cancellation. A complete canonical final replaces/reconciles the current text;
it is never appended to the text already streamed.

Acceptance uses controllable incremental model fixtures rather than requiring
live provider calls:

- Pause the model before its terminal response and assert that an external
  Runtime consumer already received a fragment; buffered replay cannot pass.
- Fail after partial primary text and verify the degraded attempt resets it,
  streams live, and cannot receive stale primary deltas.
- Fail the degraded attempt and verify deterministic replacement and completion.
- Cancel during generation and verify cleanup, no subsequent text, and no fallback.
- Verify execution text never enters the answer channel and canonical final text
  equals the completed product answer without duplication.
- Preserve tool activity order, recoverable tool failures, no-tool success,
  tracing, and focused context-governance checks affected by the change.

Phase exit: a consumer without a browser can observe live execution, answer
growth, replacement, and final completion correctly. HTTP/browser delivery is
the separate Phase 3 acceptance boundary.

This Runtime event behavior does not make the current HTTP protocol express
attempt reset. Product/transport integration must select the new attempt and
clear failed text before browser fallback replacement can be considered
supported.

### Phase 3: minimal transport and converter loop

Design approved; implementation and executable acceptance are pending. Connect
send -> activity -> live answer -> optional fallback replacement -> completion
and persistence through a real HTTP/browser path. Include a minimal frontend
converter here; polished process UI belongs to Phase 5.

**Decision:** AssistantTransport owns state replication; Product retains business
completion and persistence. Cancel unfinished generation when the connection
disconnects, rather than continuing it in the background.

**Reason:** A shared stream implementation removes duplicate parsing while
preserving DotaMind's server authority. Disconnect cancellation keeps resource
ownership bounded without adding first-version resume infrastructure.

**Not included:** Background generation after disconnect, automatic reconnect or
replay, frontend tool execution, arbitrary client model configuration, or silent
fallback to the old protocol.

Switching the selected thread is not a disconnect: Phase 4 keeps that thread's
connection and state alive outside the selected view. Generation in an unselected
thread is supported while the page and its connection remain alive.

Pin compatible frontend/Python versions and verify API exports, wire encoding,
stream termination, and cancellation behavior in a minimal connection before
connecting Runtime. Use the library's encoder/decoder rather than implementing
another custom parser. HTTP EOF alone does not establish successful generation
or persistence; explicit product outcomes remain authoritative.

Requests associate the user input with a session, request identity, and message
identity. Preserve browser/session authorization, server-owned history, and
request idempotency. Client-supplied state cannot overwrite those facts or
configure the model. Accept only commands needed by this first-version path.
Saving the same completed result reuses the request identity; intentionally
generating a new answer starts a new execution request. Do not confuse the two.

Map product mutations to transport updates instead of resending all history for
each event:

| Product change | Transport/converter behavior |
| --- | --- |
| Stage or tool activity changes | Update the relevant state fields/activity item |
| Answer fragment | Append text to the active answer attempt |
| Fallback starts | Switch attempt and clear text in one coherent state update |
| Canonical completion | Reconcile text and confirm ready/completed without duplication |
| Save result | Update persistence and reconcile durable message identity |

The converter updates the same assistant message throughout. It does not decide
fallback policy or maintain a second independent answer lifecycle. An optimistic
user message must reconcile with server acceptance rather than appear twice;
the transition from generating to saved must not create a second assistant
message. Full history/thread integration follows in Phase 4, but identity
handoff is part of this phase.

The minimum frontend displays activity/stage, growing answer text, a stop action,
and cancellation/error/persistence status. User stop propagates through transport
to Runtime and the active model call. When the server detects disconnect, it
cancels unfinished generation and performs cleanup; it must not start fallback
because of cancellation. Detection is not necessarily instantaneous, so existing
Runtime deadlines still bound work. A final answer already entering persistence
is not rolled back merely because the browser disconnects. Later history is
authoritative for any committed result.

Without terminal confirmation, the client settles its busy state and reports
connection interruption. It must not infer save success or request fallback for
a network error. No promise is made that the disconnected client receives the
server's terminal cancellation event.

Old and new routes may coexist briefly during development, but a request uses
exactly one route. Do not dual-send or transparently retry an unsuccessful new
transport request through the old protocol: either could run the Agent twice.
Phase 3 validates the new route; Phase 4 integrates the remaining message/history
features, switches the normal path, and removes the old protocol.

Acceptance through real HTTP and a browser (using a controllable model fixture
where useful):

- Text reaches the browser before model completion; server/proxy response
  buffering does not turn it into whole-answer delivery.
- Fallback resets the answer and cannot mix old-attempt fragments into new text.
- Stop and detected disconnect cancel unfinished backend generation and do not
  merely hide client activity.
- A save failure preserves the answer; same-request save retry neither reruns
  the model nor duplicates a turn.
- Truncated streams settle the client with an interruption rather than leaving
  it running forever or falsely reporting completion.
- Optimistic/accepted user identity and generating/saved assistant identity
  reconcile, and canonical completion does not duplicate streamed text.

### Phase 4: messages, history, and independent thread runs

Design approved; implementation and executable acceptance are pending.

**Decision:** Switching threads changes the selected view only. Existing runs
continue receiving streamed text and saving their final answers. Render only
standard Markdown in this version, without catalog entity enhancement.

**Reason:** Users can inspect or use another conversation without abandoning an
answer. A shared Markdown renderer keeps live/history behavior consistent without
expanding this migration into a visual-entity feature.

**Not included:** Cross-tab coordination, continuing after actual disconnect,
resuming streams after reload, new edit/branch/regenerate features, or enhanced
entity rendering. Existing stored visual metadata need not be deleted.

Own per-thread connections and run state outside the currently selected view.
Reuse assistant-ui's thread/runtime facilities where they satisfy this lifecycle;
inspect their actual behavior before adding only the missing ownership support.
Selection changes must not unmount/abort another active thread's connection.
Users may start a run in B while A continues. This does not introduce concurrent
runs within the same thread. Route every update by thread, request, message, and
answer-attempt identity so text, errors, cancellation, and save outcomes cannot
leak across conversations. Stop targets only the corresponding thread's run.

Returning to A shows its current growing answer, completed answer, fallback, or
save error. Retain that state during the live page session, including completed
but unsaved text; loading older repository history must not erase an active or
unsaved answer. After a successful save, reconcile with the same message rather
than append another one. Show an unread indicator when an unselected thread
completes. Refresh restores saved dialogue only; no durable draft store is added.

| User action / connection event | Required behavior |
| --- | --- |
| Select another thread | Keep original generation, stream consumption, and saving active |
| Return to a thread | Render its latest in-memory state and continue updates |
| Stop a run | Cancel that run only; no cancellation-triggered fallback |
| Refresh/close page or actual connection loss | On server detection, cancel unfinished generation as specified in Phase 3 |
| Disconnect after canonical generation | Do not promise rollback of saving; repository history remains authoritative |

Live and restored messages share one canonical message conversion and Markdown
renderer. Preserve request/message identity across optimistic user acceptance,
streaming, save completion, and history hydration. Historical messages without
process data do not fabricate activity panels. Remove decorateCatalogMentions
from the normal display path. Visual metadata may stay stored but must not be
required for readable answers or consumed for entity enhancement. Preserve trace
links and existing message actions through structured metadata; this restriction
is about catalog visuals, not all metadata.

Retire the old NDJSON encoder/parser, transport event types, accumulated-text
converter, and superseded lifecycle logic after the new path is accepted. Retain
or relocate still-needed history, authorization, session, and trace operations
rather than deleting whole files solely because they also contained old transport
code. The normal chat path must use one protocol without automatic legacy retry.

Acceptance:

- Run A and B concurrently; switching does not cancel either or mix their updates.
- Stop A without stopping B; return to either thread and see its actual state.
- Complete/fallback/save-fail in an unselected thread; preserve its answer and
  report its state correctly when selected, with completion unread indication.
- Reconcile live state with history without duplicate user/assistant messages
  or overwriting active/unsaved text with an older snapshot.
- Copy canonical Markdown, render live/history identically, and preserve ordinary
  Markdown links/images without injecting catalog decorations.
- Retry saving without regeneration; refresh restores committed text and does
  not claim recovery of unpersisted answers or ephemeral activity.
- Existing trace/actions remain usable and the normal path works after removal
  of the old streaming protocol.

### Phase 5: process UI

Build the execution activity, tool timeline, and final answer presentation.
Render Markdown incrementally as answer fragments arrive, including partial
Markdown constructs, while preserving the user's ability to scroll/read.
Implement default folding after final readiness, manual reopening, and visible
failure/cancellation/persistence outcomes without copying those rules to Runtime.

Acceptance: progress reflects real events, ordering survives repeated tool/model
cycles, and users can inspect the process after completion in the current view.
The final answer grows visibly during generation; completion, interruption,
and fallback replacement leave a coherent message without a fake typing replay.

### Phase 6: regression and cleanup

Complete integration regression and remove obsolete state/transport code.
Exercise no-tool success, multiple tools, recoverable tool failure, fatal error,
primary/degraded/deterministic answers, cancellation, truncated streams, database
failure and retry, consecutive turns, thread switching, and refresh after save.
Include first-fragment delivery before completion, cancellation/failure after
partial text, fallback replacement after partial text, and final text equality
between the live message and saved history.

Acceptance: deterministic focused checks and frontend/backend integration checks
protect the complete user journey. Report actual checks and limitations; do not
claim resumability or durable execution recovery. Real-provider/model runs are
not required merely to validate transport mechanics.

## Reference baseline

- [AssistantTransport](https://www.assistant-ui.com/docs/runtimes/custom/assistant-transport)
- [Runtime adapters](https://www.assistant-ui.com/docs/runtimes/concepts/adapters)

These references establish the state/converter approach, not a permanently
fixed library API. Verify the installed versions during Phase 3. Do not copy a
reference backend's client-owned state handling over DotaMind's server-owned
history and authorization boundary.
