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
  "session_id": "optional UUID v4"
}
```

`session_id` is optional. Omitting it runs a stateless request. Reusing it
enables compact `Turn` memory for the same user security subject.

Response fields include:

- `status`: `ok`, `clarification_required`, `insufficient_context`,
  `insufficient_tools`, `insufficient_evidence`, or `error`.
- `response_type`: `direct_answer`, `clarification`,
  `conversation_context_missing`, `capability_boundary`, a tool answer
  contract, `tool_error`, `answer_error`, `execution_error`, `planning_error`,
  `decision_validation_error`, or `insufficient_evidence`.
- `decision_kind` and `missing_fields`.
- `plan` and `tool_results` for tool decisions.
- `planner_required_evidence`, `effective_required_evidence`, and
  `required_evidence_sources`.
- `evidence_graph`, `answer`, and `review` when that branch creates them.
- `errors`, `error_code`, and `trace`.
- required `runtime`: UUID4 run id, duration, terminal stage, budget limits and
  usage, plus one sanitized attempt summary.

The public attempt contains index, decision kind, status/failure stage,
duration, tool call status/latency, evidence summary, answer type/status/
confidence, and critic pass/severity/issue count. It never contains plan goal
or args, ToolResult data/error/source/metadata, internal dispatch records,
answer text, critic reasons, history, session/request ids, prompts, Controller
raw output, or validation/retry content. A stateful safe failure still includes
runtime but reduces its attempt to index/status/failure stage/duration.

For session requests, internal history, the rendered history block, raw
Controller output, retry feedback and validation details are not serialized.
Invalid Controller/plan results use a redacted failure envelope and a redacted
failure `Turn`.

Within `evidence_graph`, registry minimum evidence is tracked by
`mandatory_evidence_by_call`. Missing per-call proof is reported as
`<tool_call_id>:<evidence_kind>`. Unclassified runtime failures use
`error/execution_error` rather than a successful raw-results response type.

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
