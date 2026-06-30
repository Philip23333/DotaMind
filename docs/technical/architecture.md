# Architecture

MetaMind now uses a single agentic backend path. The old canonical v2.1 fixed
report pipeline has been deleted.

## Backend Layout

```text
app/
  api/v1/          /plan schemas, route, and mapper
  application/     PlanService
  agentic/         planner, LangGraph runner, tools, evidence, answer, critic
  integrations/    OpenDota, STRATZ, patch-note clients and deterministic helpers
  config/          policy.yaml business policy
  resources/       prompts and /debug/plan asset
```

There is no `app/pipeline/` or old report domain layer. New capabilities should
be exposed as deterministic agentic tools and output contracts, not as fixed
business pipelines.

## Runtime Workflow

```text
POST /api/v1/plan
  -> PlanService
  -> AgentGraphRunner
  -> LangGraph StateGraph(AgentRunState)
      -> planner_node
      -> validate_plan_node
      -> tool_executor_node
      -> evidence_node
      -> answer_node
      -> critic_node
      -> response_node
```

The planner creates a constrained `ExecutionPlan`. Code validates and executes
registered tools, builds an `EvidenceGraph`, synthesizes an answer, runs a critic,
and serializes the final response.

Missing tools, invalid plans, upstream tool errors, and insufficient evidence are
surfaced directly. There is no fallback to deleted report endpoints.

## Component Roles

| Component | Type | LLM | Responsibility |
|---|---|---:|---|
| `AgenticPlanner` | Agent | yes | Create constrained execution plans |
| `ToolExecutor` | Runtime | no | Validate and execute registered tool calls |
| Agentic tools | Tools | no | Fetch structured evidence from OpenDota, STRATZ, patch data, and local constants |
| `EvidenceGraph` builder | Runtime | no | Extract evidence from tool results |
| `AnswerSynthesizer` | Agent/rules | optional | Produce structured or natural-language answers from evidence |
| `AgenticCritic` | Rules | no | Review missing evidence, tool failures, mock usage, and confidence |
| `response_node` | Runtime | no | Serialize public `/api/v1/plan` response shape |

## Debugging

Use:

```text
http://localhost:8001/debug/plan
```

The deprecated Next.js app under `apps/web` should not be modified unless
explicitly requested.

## Migration Status

- Deleted `/api/v1/query` and structured report endpoints.
- Deleted `/api/v1/services` and `/debug/chat`.
- Deleted `application/query_service.py`, `application/report_service.py`,
  `application/catalog.py`, `app/pipeline/`, and old report/task/evidence domain
  models.
- Kept `/api/v1/plan`, `/debug/plan`, and `/health`.
- Moved team resolution into an OpenDota integration helper used by agentic tools.
