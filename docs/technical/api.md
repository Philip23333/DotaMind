# API

Base URL:

```text
http://localhost:8001
```

## Health

```http
GET /health
```

## Agentic Plan

```http
POST /api/v1/plan
```

Request:

```json
{
  "game": "dota2",
  "query": "enemy picked Lina, what should I pick?"
}
```

Response fields:

- `status`: `ok`, `insufficient_tools`, or `error`
- `response_type`: final response category, such as `draft_advice` or
  `capability_boundary`
- `plan`: planner-produced `ExecutionPlan`
- `tool_results`: deterministic tool execution results
- `evidence_graph`: extracted evidence and quality metadata
- `answer`: synthesized answer, when available
- `review`: critic review, when available
- `errors`: validation or execution errors
- `trace`: node trace
- `planner_output`, `planner_raw_content`, `planner_finish_reason`: planner
  debugging metadata

## Debug UI

```http
GET /debug/plan
```

Serves the internal plan console for querying `/api/v1/plan` and inspecting raw
state.

## Removed Endpoints

The old fixed report/query surface has been deleted and returns FastAPI 404:

- `GET /api/v1/services`
- `POST /api/v1/query`
- `POST /api/v1/meta-report`
- `POST /api/v1/patch-impact`
- `POST /api/v1/team-report`
- `POST /api/v1/verify-claim`
- `GET /debug/chat`

No compatibility redirect, adapter, or fallback is provided.
