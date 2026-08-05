# API

Base URL: `http://localhost:8001`.

## Anonymous Chat Sessions

The browser chat client generates one UUID v4 and persists it locally. All session
endpoints require `X-DotaMind-Browser-Id: <UUID v4>`; the server stores only a SHA-256
hash and uses it as the ownership boundary. These endpoints manage the complete durable
transcript in PostgreSQL:

```http
POST   /api/v1/chat/sessions
GET    /api/v1/chat/sessions
GET    /api/v1/chat/sessions/{session_id}
PATCH  /api/v1/chat/sessions/{session_id}
DELETE /api/v1/chat/sessions/{session_id}
```

`POST` creates an empty `dota2` session. `PATCH` accepts either `{ "title": "..." }`
(1–80 characters) or `{ "is_pinned": true|false }`; the first completed turn automatically
supplies a title unless it was customized. `GET /{session_id}` returns the ordered transcript, including the stored
allowlisted public response and compact memory metadata. A session or transcript belonging
to another browser is indistinguishable from missing and returns `404`; missing or invalid
browser identity returns `422`.

Session lists return `is_pinned` and order pinned sessions first, followed by the most recently
updated unpinned sessions. Pinning does not change the conversation's `updated_at` activity time.

Stateful `/plan` and `/plan/stream` calls use the same session ownership boundary and
require `session_id`, `request_id`, and the browser header. PostgreSQL commits each
completed turn and allocates a strictly increasing fencing token for the idempotent
replay/conflict record; Redis only coordinates the short-lived lease for concurrent workers.
If the delete lock cannot be acquired, deletion returns `409 chat_busy`. A successful
PostgreSQL delete returns `204`; Redis cleanup is performed while the lock is held and a
cleanup failure is logged without undoing the durable delete. Repeating a delete for a
missing session returns the stable `404 chat_not_found` response.

## Health

```http
GET /health
```

## Controller Request

```http
POST /api/v1/plan
```

```json
{
  "game": "dota2",
  "query": "我上次问的是什么英雄来着",
  "session_id": "optional UUID v4",
  "request_id": "optional UUID v4; requires session_id"
}
```

`session_id` is optional. Omitting it runs a stateless request. Reusing it
enables compact `Turn` memory for the same user security subject.

`request_id` is optional and currently supported only with `session_id`. It
identifies one logical stateful request using `(session_id, request_id)`: replaying
the same validated `query` and `game` returns the original public response,
including the original `runtime.run_id`, without running the Graph or appending
another Turn. Reusing the same key with different inputs returns HTTP 409:

```json
{
  "query": "...",
  "game": "dota2",
  "session_id": "UUID v4",
  "status": "error",
  "reason": "request_id has already been used with different request inputs",
  "response_type": "idempotency_conflict",
  "error_code": "idempotency_conflict"
}
```

This pre-execution conflict has no `runtime`; it does not create a Run, Attempt,
or Session Turn. Supplying `request_id` without `session_id` is a 422 validation
error. The memory-backend replay window is bounded by request-record TTL/capacity.
When `DOTAMIND_SESSION_STORE_BACKEND=redis`, the same semantics are shared by Redis-backed
workers; Redis Server restart durability still depends on the deployment's AOF/RDB and volume setup.

When the configured SessionStore is unavailable, locked past its acquisition deadline, loses its
lease, or detects invalid persisted data, `/plan` returns HTTP 503:

```json
{
  "status": "error",
  "response_type": "session_store_error",
  "error_code": "session_store_error"
}
```

This envelope has no `runtime`; Redis errors never fall back to stateless or memory execution.

Response fields include:

- `status`: `ok`, `clarification_required`, `insufficient_context`,
  `insufficient_tools`, `insufficient_evidence`, or `error`.
- `response_type`: `direct_answer`, `clarification`,
  `conversation_context_missing`, `capability_boundary`, a tool answer
  contract, `tool_error`, `answer_error`, `execution_error`,
  `execution_budget_error`, `execution_timeout`, `planning_error`,
  `decision_validation_error`, `insufficient_evidence`, `replan_exhausted`, or
  `idempotency_conflict` for the 409 pre-execution envelope.
- `decision_kind` and `missing_fields`.
- `plan` and `tool_results` for tool decisions.
- `planner_required_evidence`, `effective_required_evidence`, and
  `required_evidence_sources`.
- `evidence_graph`, `answer`, and `review` when that branch creates them.
- `errors`, `error_code`, and `trace`.
- required `runtime`: UUID4 run id, duration, terminal stage, budget limits and
  usage, plus one or two sanitized attempt summaries.

The public attempt contains index, decision kind, status/failure stage,
`recovery_code`, duration, tool call status/latency/`reused`, evidence summary, answer type/status/
confidence, and critic pass/severity/issue count. It never contains plan goal
or args, ToolResult data/error/source/metadata, internal dispatch records,
answer text, critic reasons, history, session/request ids, prompts, Controller
raw output, or validation/retry content. A stateful safe failure still includes
runtime but reduces each attempt to index/status/failure stage/recovery code/duration.

`recovery_code` is `null` for Attempt 0 and `missing_evidence` only for an
Attempt 1 that was actually started by Recovery. The top-level plan/tool results/
evidence/answer/review always come from the final Attempt; earlier Attempts expose
only the allowlisted runtime summary.

For session requests, internal history, the rendered history block, raw
Controller output, retry feedback and validation details are not serialized.
Invalid Controller/plan results use a redacted failure envelope and a redacted
failure `Turn`.

Within `evidence_graph`, registry minimum evidence is tracked by
`mandatory_evidence_by_call`. Missing per-call proof is reported as
`<tool_call_id>:<evidence_kind>`. Unclassified runtime failures use
`error/execution_error` rather than a successful raw-results response type.
Only plain global missing-evidence kinds can trigger the single bounded Replan;
per-call missing proof, tool/extractor failures and Critic failures remain terminal.

## Streaming Controller Request

```http
POST /api/v1/plan/stream
Content-Type: application/json
Accept: application/x-ndjson
```

The request body is the same `PlanRequest` used by `/api/v1/plan`. Validation
happens before the response starts, so malformed input still receives ordinary
HTTP 422. A valid request returns `application/x-ndjson`; each UTF-8 line is one
JSON object and the final line is exactly one `result` or `error` event:

```json
{"type":"phase","phase":"planning","attempt_index":0}
{"type":"tool","tool_call_id":"call_1","tool":"stratz.hero_matchup_ranking","attempt_index":0,"status":"running","latency_ms":null,"reused":false,"failure_code":null}
{"type":"answer_delta","delta":"新增文本","attempt_index":0,"provisional":true}
{"type":"result","session":{"session_id":"UUID","title":"首轮问题","updated_at":"..."},"response":{"status":"ok","answer":{},"runtime":{}}}
```

- `phase` is emitted for planning, tool execution, answer synthesis and critic
  review.
- `tool.running` is emitted immediately before a validated tool enters its
  handler. Reused calls, reference-resolution failures, pre-dispatch runtime
  gates and handler failures emit only their safe terminal `ok`/`error` event.
- `answer_delta` is emitted only for the natural-language synthesizer's real
  upstream model stream. Direct replies and deterministic structured answers
  wait for the final `result`; no typing simulation is used.
- `result.response` has the same public response contract as `/api/v1/plan`,
  including idempotency replay. Once the stream has started, conflicts,
  SessionStore failures and execution failures use a terminal `error` event
  because HTTP headers can no longer change.
- A persistent stateful result may include `session` with the updated summary. The
  first completed turn's automatic title can therefore update the client sidebar
  without reloading the transcript; title synchronization is best-effort on the client.

Events are an allowlist: they never contain tool parameters or results, history,
prompts, model raw output, secrets, raw exceptions or internal dispatch state.
Clients should discard provisional deltas unless the final `result.response.status`
is `ok`; a Critic or execution failure makes the final public response authoritative.

The route sends `Cache-Control: no-cache, no-transform` and
`X-Accel-Buffering: no`. A reverse proxy in front of the service must also disable
response buffering for this path, otherwise genuine upstream token deltas will be
held until completion. This first version intentionally has no reconnect,
heartbeat, background recovery or cross-page conversation restoration.

## Debug UI

```http
GET /debug/plan
```

This is the only internal query UI. It displays both no-tool decisions and the
conditional tool/evidence path, plus Run/Attempt/Budget and timed trace data.

## Removed Endpoints

The old fixed report/query surface returns 404. No redirects or compatibility
adapters are provided:

- `GET /api/v1/services`
- `POST /api/v1/query`
- `POST /api/v1/meta-report`
- `POST /api/v1/patch-impact`
- `POST /api/v1/team-report`
- `POST /api/v1/verify-claim`
- `GET /debug/chat`
