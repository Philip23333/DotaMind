# API

Base URL: `http://localhost:8001`.

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
error. The memory-backend replay window is bounded by request-record TTL/capacity;
Redis and multi-worker idempotency are not implemented yet.

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
