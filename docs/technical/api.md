# API

Base URL: `http://localhost:8001`.

## Anonymous Chat Sessions

An anonymous client generates one UUID v4 and persists it locally. All session
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
allowlisted public response and compact audit metadata. Full user and assistant
messages come from PostgreSQL transcript columns, not from the compact summary. A session or transcript belonging
to another browser is indistinguishable from missing and returns `404`; missing or invalid
browser identity returns `422`.

Session lists return `is_pinned` and order pinned sessions first, followed by the most recently
updated unpinned sessions. Pinning does not change the conversation's `updated_at` activity time.

Chat Run requests use the session ownership boundary and the browser header. PostgreSQL
commits each completed Turn and Run state, allocates a strictly increasing fencing token,
and Redis carries replayable events plus cancel notifications.
If the delete lock cannot be acquired, deletion returns `409 chat_busy`. A successful
PostgreSQL delete returns `204`; Redis cleanup is performed while the lock is held and a
cleanup failure is logged without undoing the durable delete. Repeating a delete for a
missing session returns the stable `404 chat_not_found` response.

## Health

```http
GET /health
```

## Offline Catalog Images

英雄和非配方物品图片随提交的 Catalog 快照保存在 API 本地，并通过现有 `/api/`
边界访问：

```http
GET /api/v1/assets/dota/heroes/{hero_id}.png
GET /api/v1/assets/dota/items/{item_id}.png
```

`resolve_hero`、`dota.hero_attributes`、`resolve_item` 和 `dota.item_info` 的
实体结果包含 origin-relative `image_path`。图片只在离线维护命令
`python apps/api/scripts/sync_game_data.py --images-only` 中从官方 CDN 下载；
请求处理不会访问外部图片服务。

`opendota.match_details` 的 `data.matches[].summary.players[]` 与
`data.matches[].draft.draft[]` 在 Catalog 成功解析时分别携带 `hero_image_path`；装备、
背包和中立物品详情携带 `item_image_path`。这些字段复用上述本地静态路径，Catalog
未命中或缺失 ID 时为 `null`，并随原有工具结果和 EvidenceGraph 透传，不新增工具或
evidence kind。

## Controller Request

```http
POST /api/v1/plan
```

```json
{
  "game": "dota2",
  "query": "enemy picked Lina, what should I pick?"
}
```

`PlanRequest` is intentionally stateless. Supplying `session_id`, `request_id` or another
unknown field returns HTTP 422; durable multi-turn work must use the Chat Run endpoints below.

Response fields include:

- `status`: `ok`, `clarification_required`, `insufficient_context`,
  `insufficient_tools`, `insufficient_evidence`, or `error`.
- `response_type`: `direct_answer`, `clarification`,
  `conversation_context_missing`, `capability_boundary`, a tool answer
  contract, `tool_error`, `answer_error`, `execution_error`,
  `execution_budget_error`, `execution_timeout`, `planning_error`,
  `decision_validation_error`, `insufficient_evidence`, or `replan_exhausted`.
- `decision_kind` and `missing_fields`.
- `plan` and `tool_results` for tool decisions.
- `planner_required_evidence`, `effective_required_evidence`, and
  `required_evidence_sources`.
- `evidence_graph`, `answer`, and `review` when that branch creates them.
- `errors`, `error_code`, and `trace`.
- required `runtime`: UUID4 run id, duration, terminal stage, budget limits and
  usage, plus one or two sanitized attempt summaries.

The public attempt contains index, decision kind, status/failure stage,
`recovery_code`, duration, tool call status/latency/`reused`, `handler_entered`,
`dispatch_stage`, and a stable tool `failure_code`, evidence summary, answer type/status/
  confidence, and critic pass/severity/issue count. It never contains plan goal
  or args, ToolResult data/error/source/metadata, internal dispatch records,
  answer text, critic reasons, history, session/request ids, prompts, Controller
  raw output, or validation/retry content. Public tool failure codes are limited to
  safe categories such as `reference_resolution_error`, `validation_error`,
  `handler_error`, `tool_error`, and `execution_timeout`; raw exceptions and reference
  paths are never serialized.

`recovery_code` is `null` for Attempt 0 and `missing_evidence` only for an
Attempt 1 that was actually started by Recovery. The top-level plan/tool results/
evidence/answer/review always come from the final Attempt; earlier Attempts expose
only the allowlisted runtime summary.

For a named recurring competition, the Controller may omit the edition year and let
the PandaScore resolver select the latest edition. When a year is explicit, the
resolver forwards it to PandaScore Series as `filter[year]` before name ranking; a
missing historical edition remains `not_found` rather than falling back to another
year.

Internal history, the rendered history block, raw Controller output, retry feedback and
validation details are not serialized. Invalid Controller/plan results use a redacted
failure envelope.

Within `evidence_graph`, registry minimum evidence is tracked by
`mandatory_evidence_by_call`. Missing per-call proof is reported as
`<tool_call_id>:<evidence_kind>`. Unclassified runtime failures use
`error/execution_error` rather than a successful raw-results response type.
Only plain global missing-evidence kinds can trigger the single bounded Replan;
per-call missing proof, tool/extractor failures and Critic failures remain terminal.

## Stateless Debug Streaming

```http
POST /api/v1/plan/stream
Content-Type: application/json
Accept: application/x-ndjson
```

The request body is the same stateless `PlanRequest` used by `/api/v1/plan`.
Validation happens before the response starts, so stateful fields receive ordinary
HTTP 422. This endpoint is for `/debug/plan` only; formal chat uses Chat Run events.

```json
{"type":"phase","phase":"planning","attempt_index":0}
{"type":"tool","tool_call_id":"call_1","tool":"stratz.hero_matchup_ranking","attempt_index":0,"status":"running","latency_ms":null,"reused":false,"failure_code":null}
{"type":"answer_delta","delta":"新增文本","attempt_index":0,"provisional":true}
{"type":"result","session":null,"response":{"status":"ok","answer":{},"runtime":{}}}
```

- `phase` is emitted for planning, tool execution, answer synthesis and critic
  review.
- `tool.running` is emitted immediately before a validated tool enters its
  handler. Reused calls, reference-resolution failures, pre-dispatch runtime
  gates and handler failures emit only their safe terminal `ok`/`error` event.
- Terminal tool events may include `handler_entered` and `dispatch_stage`; clients
  should display an error with `handler_entered=false` as “未执行” rather than a
  misleading zero-millisecond handler duration.
- `answer_delta` is emitted only for the natural-language synthesizer's real
  upstream model stream. Direct replies and deterministic structured answers
  wait for the final `result`; no typing simulation is used.
- `result.response` has the same public response contract as `/api/v1/plan`.
  Once the stream has started, execution failures use a terminal `error` event
  because HTTP headers can no longer change.

Events are an allowlist. By default they never contain tool parameters or results,
history, prompts, model output, secrets, raw exceptions or internal dispatch state.
When the local-test-only `DOTAMIND_TEST_OBSERVER_ENABLED=true` flag is set, an
additional `observer` event carries complete Controller/Answer message arrays and
model output plus planned/resolved tool args and ToolResult output. These events
remain in the short-lived Run event stream and are not added to the public result
or PostgreSQL transcript; the flag must not be enabled in a public environment.
Clients should discard provisional deltas unless the final `result.response.status`
is `ok`; a Critic or execution failure makes the final public response authoritative.

The route sends `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no`.
It is not a durable chat execution path and does not provide Run recovery or cancellation.

## Chat Run Lifecycle

All formal browser chat execution uses these endpoints. Every request requires a UUID v4
`X-DotaMind-Browser-Id`; ownership failures are intentionally indistinguishable from missing
resources (`404 not_found`).

```http
POST /api/v1/chat/sessions/{session_id}/runs
GET  /api/v1/chat/runs/{run_id}
GET  /api/v1/chat/sessions/{session_id}/active-run
GET  /api/v1/chat/runs/{run_id}/events?after=N
POST /api/v1/chat/runs/{run_id}/cancel
```

Creation accepts `{ "request_id": "UUID v4", "query": "...", "game": "dota2" }` and
returns `202` with a queued Run. Repeating the same request/payload returns the same Run;
payload conflicts or another active Run in the same session return `409`.

Run events are replayable NDJSON envelopes with `run_id`, `session_id`, monotonically increasing
`sequence` and allowlisted phase/tool/delta/result/status data, plus test-only `observer` data
when explicitly enabled. `after=0` is the page-refresh
recovery path. Heartbeats are not persisted. If Redis events are missing after PostgreSQL has
reached a terminal state, the API emits a synthetic `transcript_recovery` status event.

Cancel persists `cancel_requested` in PostgreSQL before local/Redis wake-up. A repeated cancel
is `202`; terminal Runs return `409 run_terminal`. Disconnecting an event subscriber only closes
the observer; it never cancels the detached background Run.

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
