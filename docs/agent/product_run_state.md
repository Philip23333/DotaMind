# Product Run State and Chat Transport

## Status and scope

This document defines the accepted target for the chat execution experience.
Phases 1-6 are implemented, including Markdown-only rendering, independent
thread runs, and removal of the obsolete chat NDJSON protocol. The product Run
State schema, Runtime-event adapter, persistence, completed-answer retry,
repository replay, and AssistantTransport endpoint are implemented. The
production `runtime-provider` uses `/transport`; the page-lifetime thread
registry keeps each thread's connection and run state alive when selection
changes. The frontend reconciles request/message identities, streams canonical
Markdown, and tracks unread counts per session in browser storage. Selecting a
thread clears only its unread count, and the sidebar reads that local state
directly. Runtime-confirmed commentary, bounded Run State projection,
authoritative execution timing, transport conversion, and the compact timeline
are implemented. The panel stops showing a running tool as active after
connection termination and uses confirmed Chinese labels, adjacent-call grouping,
and one-time folding on Answer Stage entry. Real model text observation remains
pending. Deterministic regression coverage uses the state stream; the separate
`/runs` Test Observer event stream remains an independent feature.
前端已接入 `/transport`，页面内多会话连接与按会话未读状态已实现；紧凑时间线展示有序工具活动和整段过程说明，并按后端事实显示执行计时。真实模型文本的阅读效果仍待观察。
Code remains the authority for current behavior. This document owns the product
Run State contract; `../ROADMAP.md` owns delivery order.

The target first version exposes real execution activity, bounded ordinary
commentary from accepted tool-call responses, tool progress, and a final answer
streamed as it is generated. It keeps canonical answer text separate from
presentation metadata and makes generation, cancellation, and persistence
outcomes explicit.

Not included: raw model reasoning display, an extra model call to generate
progress summaries, resumable streams, cross-tab synchronization, durable
execution recovery, or a full trace viewer. Refresh restores saved dialogue; it
does not promise to reconnect to an in-flight run. The execution-timer UI
described below is implemented. Ordinary execution commentary and backend
execution timing cross the transport, and the compact timeline renders
commentary, tool groups, status, and duration.

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
exact wire field names and activity/error shapes remain implementation details.
The execution-commentary display bound and reuse of the existing activity-count
bound are specified below. Prefer the smallest shape satisfying these invariants.

```ts
type RunState = {
  requestId: string;
  assistantMessageId: string;
  status: "running" | "completed" | "failed" | "cancelled";
  stage: "execution" | "answer";
  activity: ActivityItem[];
  execution_timing: {
    started_at: string;
    finished_at: string | null;
    duration_seconds: number | null;
  } | null;
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
Frontend connection outcomes carry their request ID and affect only that request's
messages and local busy state; they do not rewrite the server Run State.

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
| Response-level tool batch rejected | Target behavior: show every call as not executed with its paired error result; do not mark a handler as successful |
| Answer stage entered | Set stage to answer even before answer text exists |
| Answer text delta received | Append to the current answer attempt immediately; answer streaming, Runtime still running |
| Answer generation fails | Replace the failed attempt with fallback in the same message; do not preserve its text as the active answer |
| Canonical final produced | Answer ready, Runtime completed; begin saving |
| Save succeeds | Persistence saved; retain canonical message identity |
| Save fails | Keep ready answer and completed Runtime status; expose persistence failure separately |
| Runtime fails before final | Failed run with a safe execution error; no synthetic successful answer |
| User cancellation before final | Cancelled run; settle active process UI without declaring success |
| Connection ends without terminal confirmation | Stop the local busy state and report interruption; do not infer server success or failure |

### Planned model-response recovery state

The response-recovery design is confirmed, but its Runtime and UI implementation
are pending in [`model_output_and_recovery.md`](model_output_and_recovery.md).
Correction exhaustion first ends execution and enters the existing Answer Stage;
it does not jump directly to `degraded_answer`. Completed TaskState items remain
completed, incomplete items remain incomplete, and the absence of a task plan does
not imply full completion. A partial answer identifies the missing scope; without
reliable completed results, the answer clearly reports failure.

Primary or degraded answer text ending with `finish_reason=length` is a failed
attempt, never a canonical final. The existing answer-attempt replacement
mechanism clears the failed text before publishing a replacement. A successful
delivered answer may make Runtime `completed`, while execution end reason and
task coverage stay separate. A rejected tool activity is explicitly “not
executed”; it is distinct from a tool handler that ran and failed.

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

An initiated save uses one finite application-level persistence budget (15 seconds
by default) for the repository write and its cooperative cancellation cleanup.
On timeout, keep the completed answer and its cache; report persistence failure
because commit outcome may be uncertain. A retry checks the idempotent repository
record first, replays it if present, and otherwise retries saving the cached
answer without rerunning Runtime. Optional visual metadata enrichment failure
uses empty metadata and does not block canonical text persistence; actual
repository failures remain visible.

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
block followed by one tool block. The timeline preserves occurrence order while
hiding stage rows; stage events still form boundaries between adjacent tool
groups. The target folding behavior is specified below and is implemented.

Stream final-answer text as the model produces it in the first version. A short
pending indicator before the first fragment is allowed, but a persistent
"generating answer" placeholder followed by the whole answer does not satisfy
this requirement. Do not simulate streaming by replaying buffered completed text
with a frontend typing animation. Chunk boundaries need not match individual
tokens; fragments must reach the browser before the model call completes.

The Runtime answer path publishes deltas during model invocation while keeping
execution text and raw reasoning out of the final-answer channel. The product
projection reconciles the canonical final once, without appending it a second
time. Persistence starts only after canonical completion and must not gate live
text.

### Execution commentary and duration (implemented; real-text observation pending)

The Runtime event, product projection, transport conversion, and compact timeline
are implemented. Fixture-based tests cover the presentation contract; observation
of real model commentary remains pending. This section defines the complete
behavior and implementation status.

#### Commentary activity

Publish a commentary activity only after an execution-stage model response has
completed, the response contains tool calls, and Runtime has accepted that batch
for execution. For that response, publish its non-empty ordinary `content` once,
then publish the corresponding tool-start and terminal activities in their real
order. The commentary is a separate activity with its own stable identity in the
existing ordered activity list; the implementation uses `commentary:<step>`.
Empty content creates no activity. A no-tool
execution conclusion is not process commentary. A response-level rejected batch
creates no accepted-call commentary activity; its explicit not-executed call
results remain governed by the rejected-batch contract.

Use only the response's ordinary `content`. Do not reuse final-answer delta events,
publish both stream fragments and the completed text, infer language or intent,
rewrite the text, or read internal reasoning fields. Commentary is an intermediate
model statement, not a verified conclusion. The final answer remains on its
independent live-streaming path.

Commentary counts toward the existing ordered-activity item limit. Each displayed
commentary is capped at 2,000 Unicode code points; longer text is truncated in
the product display projection with “内容已截断”. These display bounds do not
modify model context or raw Trace evidence. The existing activity omission
indicator continues to disclose omitted items.

Tool labels are presentation-only mappings; the active registry remains the
source of which tools exist. Unknown tool IDs display as “工具调用” and do not
block activity rendering. The confirmed mapping is implemented in the frontend.

| Internal tool ID | Display label |
| --- | --- |
| `esports.league.search` | 联赛查询 |
| `esports.series.search` | 联赛届次查询 |
| `esports.series.teams` | 参赛战队查询 |
| `esports.tournament.search` | 赛事阶段查询 |
| `esports.match.search` | 对阵查询 |
| `esports.team.search` | 战队查询 |
| `esports.player.search` | 职业选手查询 |
| `hero.guide` | 英雄攻略查询 |
| `player.profile` | 玩家资料查询 |
| `player.recent_games` | 玩家近期战绩查询 |
| `game.detail` | 单局详情查询 |
| `catalog.lookup` | 游戏资料读取 |
| `artifact.grep` | 外置结果搜索 |
| `artifact.read` | 外置结果读取 |
| `task.plan` | 任务规划 |
| `task.checkpoint` | 任务进度记录 |
| `web.search` | 网页搜索 |

The frontend merges adjacent activities only when their internal tool IDs are
exactly equal. This is a display projection; underlying call identity, order, and
outcome remain unchanged. Commentary, different tools, and hidden stage activities
break a group. A group retains its count and any failed or unconfirmed outcome.
Parallel calls do not represent serial progress, and their durations are not
added together. The subtle animation applies only to **正在执行的工具文字**, not to
commentary; reduced-motion mode disables it. Commentary is published as a
complete static segment.

#### Execution duration

The backend owns the authoritative timing facts. Start timing at the
`AgentStarted` event timestamp. Normal execution duration ends at the
`AnswerStageStarted` event timestamp; final-answer generation and persistence are excluded. If
execution instead stops or fails, freeze duration at that event and expose the
corresponding terminal status rather than normal completion. Do not derive
duration by summing tool times or restart timing when a frontend component mounts.

The frontend may advance the display locally while the run is active, based on
the backend timing fact. Answer retries do not restart execution timing. If the
connection ends without terminal confirmation, stop the local clock and label
the connection as interrupted; do not present its local estimate as a
server-confirmed successful duration. Historical messages without timing data do
not receive a fabricated duration.

#### Collapse and persistence

During execution, the process area starts expanded and the user may collapse it.
On the first transition into Answer Stage, collapse it once by default. If the
user reopens it afterward, preserve that choice through answer deltas, answer
retries, and persistence updates; do not force another collapse. A component
first mounted in Answer Stage starts collapsed. A new request starts with its own
default state. Cancellation or failure before Answer Stage does not simulate a
normal stage transition. Error, stop, connection, and save-failure indicators
stay visible outside the collapsible process area.

Commentary and process activities remain ephemeral current-page display data.
Do not append commentary to the final answer, persist a process log in dialogue,
or change SessionExecutionHistory, context compaction, or Trace responsibilities.
Refresh need not reconstruct the complete timeline.

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
tests in `apps/api/tests/vnext/test_product_run_state.py`. Runtime events are
mapped by the separate Phase 2 adapter; this phase's state model remains
independent of Runtime execution, product chat, transport, and frontend. The
broader chat experience acceptance is still pending.

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

Design approved. Runtime answer-stage and answer-attempt lifecycle events, live
answer delivery during model invocation, the standalone Runtime-to-Run-State
adapter, and its use by `VNextChatService` are implemented with deterministic
tests. The service connects the state stream to dialogue persistence, cache
retry, repository replay, and trace references. Phase 3 added AssistantTransport;
Phase 6 removed the obsolete `/messages` route and terminal-only event adapter.

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
compaction text remain trace-only. The adapter in
`apps/api/app/vnext/product/runtime_projection.py` maps these events into
request-local product snapshots. `VNextChatService.stream_turn_states()` uses
the same event mapper while retaining the canonical `FinalMessage` for history,
cache, trace, and persistence. `stream_turn_states()` is the service's only chat
state-stream API; no compatibility event translation remains.

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

The standalone Runtime-to-Run-State boundary and product service integration
have deterministic coverage for live execution, answer growth, fallback
replacement, completed-answer caching, save retry, replay, and cancellation
around persistence. Product state is connected to dialogue persistence and
trace references. HTTP/browser delivery is the Phase 3 acceptance boundary.

The product state stream expresses attempt reset, and `/transport` carries those
updates to the production frontend. There is no legacy chat streaming route or
`stream_turn()` compatibility adapter.

### Phase 3: minimal transport and converter loop

The backend transport endpoint and its protocol loopback acceptance are
implemented. The browser-facing `/transport` route accepts one new user message,
projects server-owned product state using the official Python encoder, and is
covered by real loopback HTTP tests for live text, fallback replacement,
completion, persistence, and disconnect cancellation. A captured HTTP stream is
also decoded by the exact official JavaScript package version used by
assistant-ui. The production frontend is connected to this endpoint through its
runtime-provider; the old chat route and NDJSON protocol have been deleted.

The frontend has a pure state converter, canonical message identities, history
reconciliation, and canonical Markdown history conversion with deterministic
tests. The production runtime-provider and chat UI are connected to `/transport`.
The process presentation and folding behavior are implemented in Phase 5.

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
message. The pure converter, history reconciliation, and identity handoff are
implemented in the production thread integration.

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
Phase 3 validated the new route; Phase 4 integrated the remaining message/history
features and switched the normal path. Phase 6 removed the old chat protocol.

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

Implemented. The production runtime-provider uses AssistantTransport, and the
mounted chat integration covers independent thread connections, switching,
stopping one request, history reconciliation, and unread indication/clearing.

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
process data do not fabricate activity panels. The vNext history path now keeps
canonical Markdown unchanged and does not apply `decorateCatalogMentions`; the
converter carries state without catalog enhancement. The production real-time
path uses the runtime-provider and AssistantTransport. Visual
metadata may stay stored but must not be required for readable answers or consumed
for entity enhancement. Preserve trace links and existing message actions through
structured metadata; this restriction is about catalog visuals, not all metadata.

The old chat NDJSON encoder/parser, transport event types, accumulated-text
converter, and superseded lifecycle adapters have been removed. History,
authorization, session, and trace operations remain on their active routes. The
normal chat path uses AssistantTransport without automatic legacy retry. The
separate `/runs` event stream and Test Observer remain because they expose
Runtime test runs, not product chat messages.

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
- Existing trace/actions remain usable and the normal path uses
  AssistantTransport.

### Phase 5: process UI

Implemented in the production chat message view. The process panel renders
ordered commentary and adjacent tool groups, hides stage rows while preserving
them as grouping boundaries, shows omitted activity counts, and labels unfinished
tool results as unconfirmed after a local connection ends. Commentary is ordinary
wrapped text with preserved line breaks and an explicit truncation label. The
header displays a live execution timer and then the authoritative backend
duration; it stops on an unconfirmed disconnect. The canonical message body
continues to stream through the existing Markdown renderer. The panel starts open
during execution, folds on first Answer Stage entry, and preserves later user
choice. A new request does not inherit the previous request's expansion state.
Cancellation, safe execution errors, connection errors, and persistence errors
remain outside the collapsible process content. No reasoning summary is
available or inferred.

Automated acceptance covers ordered grouping, timer formatting/freeze/disconnect,
Chinese labels and unknown tools, terminal states, one-time folding, user choice,
and no empty panel for history without process metadata. Desktop and narrow
fixture-based browser review remains a visual check; real model commentary is
still pending qualitative observation. No forced scroll is added for deltas or
panel changes.

### Phase 6: regression and cleanup

Implemented. The obsolete product-chat NDJSON route, event encoder/types,
accumulated-text converter, and superseded model/history adapters are removed.
Product service tests assert `stream_turn_states()` snapshots directly; the
removed `/messages` route is covered by a regression that verifies it cannot
start a run. Session history, authorization, and trace APIs remain. The `/runs`
event stream and Test Observer are independent Runtime test-run functionality and
remain in place.

Deterministic backend and frontend regression suites are the acceptance boundary
for this phase. They do not establish reasoning summaries, resumability,
cross-tab recovery, or durable execution recovery. Real-provider/model runs are
not required to validate transport mechanics.

## Reference baseline

- [AssistantTransport](https://www.assistant-ui.com/docs/runtimes/custom/assistant-transport)
- [Runtime adapters](https://www.assistant-ui.com/docs/runtimes/concepts/adapters)

These references establish the state/converter approach, not a permanently
fixed library API. Verify the installed versions during Phase 3. Do not copy a
reference backend's client-owned state handling over DotaMind's server-owned
history and authorization boundary.
