# Architecture

> Architecture is now implemented as the canonical v2.1 pipeline: domain models, application use cases, and one Orchestrator -> Retriever -> Analyzer -> Critic -> Formatter path.

MetaMind is organized around three product surfaces:

```text
Web Dashboard
+ Callable Agent Service
+ CAP Paid Service
```

## Backend Layout

```text
app/
  api/v1/          HTTP schemas, routes, and mappers only
  application/     query/report use cases and service catalog
  domain/          evidence, task, and report dataclasses
  pipeline/        orchestrator, retriever, analyzer, critic, formatter
  data/            patch JSON + mock fixtures
  integrations/    OpenDota, STRATZ, patch-note clients
  config/          policy.yaml business policy
  resources/       prompts and internal debug UI assets
```

The application layer is deliberately decoupled from routes so future adapters can call the same code from:

- HTTP endpoints
- A2A agent handlers
- CAP order callbacks
- Scheduled report-generation jobs

## Component Roles (v2.1)

| Component | Type | LLM | Responsibility |
|---|---|---|---|
| **Orchestrator** | Agent | optional + rules | Intent parsing and task selection |
| **Analyzer** | Agent | optional | Scoring, claim generation, evidence binding, report sections |
| **Critic** | Agent | rules | Independent review, reject on missing/weak evidence |
| Retriever | Tool fn | no | OpenDota / patch JSON fetching, EvidenceBundle assembly |
| Formatter | Tool fn | no | Render domain reports to public response shape |

The classification rule: **a component is an Agent only if it requires an LLM decision**. Wrapping deterministic code as an "Agent" is rejected as noise.

## Workflow

```text
HTTP / CAP / A2A caller
  -> api/v1/routes.py
  -> api/v1/mappers.py
  -> application/query_service.py or application/report_service.py
  -> pipeline/orchestrator.py
  -> pipeline/retriever.py
  -> pipeline/analyzer.py
  -> pipeline/critic.py
  -> pipeline/formatter.py
  -> api/v1/mappers.py
```

Structured endpoints and natural-language `/api/v1/query` both use the same pipeline. `/api/v1/query/experimental` has been removed.

## Independent Failure Modes

This is what makes the multi-Agent topology meaningful rather than decorative:

- **Orchestrator** can mis-plan: wrong tool, missing tool, infinite loop
- **Analyzer** can hallucinate: claims without evidence, over-confident verdicts
- **Critic** can mis-judge: pass false claims or reject good ones

Three Agents, three independent failure surfaces, all observable in trace logs. This is the textbook Reflexion / Self-Critique pattern.

## Scoring (v2.1)

The current implementation keeps deterministic weighted scoring for reproducibility and uses the Analyzer LLM only for optional hero insight text when enabled. Tunable business policy lives in `app/config/policy.yaml`; secrets, URLs, and environment switches stay in `.env`.

Pipeline:

```text
1. Signal extraction       (deterministic, thresholds in config/policy.yaml)
2. Deterministic scoring    (Analyzer)
3. Optional LLM insight     (Analyzer)
4. Critic review            (rules)
```

Confidence remains a bounded float in the public API for frontend compatibility.

## Frontend

The legacy Next.js app is deprecated for active development. Use FastAPI's `/debug/chat` page for internal query testing unless work on `apps/web` is explicitly requested.

Main modules:

- Query console
- KPI cards
- Meta report ranking table
- ECharts score chart
- Patch impact panel
- Team intelligence panel
- Agent API / CAP service catalog

The deprecated dashboard uses backend responses when `NEXT_PUBLIC_API_BASE_URL` is reachable and falls back to local mock data while the backend is offline.

## Migration Status

- Legacy `agents/`, `services/`, and `tools/` source files have been removed.
- `application/`, `domain/`, and `pipeline/` are the only backend business architecture.
- `/api/v1/query` is the canonical natural-language endpoint.
- `app/config/policy.yaml` replaces the old `opendota.json`, `signals.yaml`, and `critic_rules.yaml` configuration sources.
- OpenDota live hero and team retrieval are implemented behind `METAMIND_LIVE_DATA_ENABLED`.
