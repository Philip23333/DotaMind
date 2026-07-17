# Architecture

MetaMind now uses a single agentic backend path. The old canonical v2.1 fixed
report pipeline has been deleted.

## Backend Layout

```text
app/
  api/v1/          /plan schemas (incl. session_id), route, and mapper
  application/     PlanService, session_store (lease-aware SessionStore transaction + InMemorySessionStore)
  agentic/
    graph.py       LangGraph StateGraph runner
    state.py       shared AgentRunState (carries injected conversation history)
    models.py      ExecutionPlan, ToolCall, ToolResult
    conversation/  Turn/ResolvedEntity models, turn summary extractor, history renderer
    nodes/         planner, validate, tools, evidence, answer, critic, response nodes
    tools/         registry, executor, hero, patch, OpenDota, STRATZ, ranking tools
    planning/      planner and output contract catalog
    evidence/      EvidenceGraph and extraction helpers
    answer/        answer synthesizer, structured and natural-language routing
    critic/        rule-first reviewer and critic rules
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

## Tool Contract Runtime

`ToolDefinition` is the single source of truth for tool field contracts:

- `input_model` defines argument type and required-field validation.
- `arg_contracts` defines argument semantics and accepted references.
- `output_paths` defines stable `$<call_id>.<output_path>` references against
  `ToolResult.model_dump(mode="json")`.
- `evidence_kinds` defines which required evidence a selected tool can produce.

Planner prompt rendering and validator rules both consume these registry
contracts. Tool-specific names such as hero or team fields must live in tool
registration metadata, tests, docs, or prompt output, not in validator branches.

Current limitation: top-level reference placeholders are type-compatible with
their target input fields. Nested references inside `list[T]` or `dict[K,V]`
are detected, but placeholder replacement is not yet fully element-type-aware.

## Component Roles

| Component | Type | LLM | Responsibility |
|---|---|---:|---|
| `AgenticPlanner` | Agent | yes | Create constrained execution plans |
| `validate_plan_node` | Runtime | no | Validate tool calls, args, references, output contracts, and evidence producibility from ToolRegistry contracts |
| `ToolExecutor` | Runtime | no | Resolve references and execute registered tool calls |
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
