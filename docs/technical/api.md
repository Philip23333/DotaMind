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
conditional tool/evidence path.

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
