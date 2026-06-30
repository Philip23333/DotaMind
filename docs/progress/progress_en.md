# MetaMind Progress

> Last updated: 2026-06-17
> Current fact: the backend has been aggressively refactored into the canonical v2.1 pipeline. Legacy `agents/`, `services/`, and `tools/` source files have been removed.

## Current Architecture

```text
api/v1/routes.py
  -> api/v1/mappers.py
  -> application/query_service.py or application/report_service.py
  -> pipeline/orchestrator.py
  -> pipeline/retriever.py
  -> pipeline/analyzer.py
  -> pipeline/critic.py
  -> pipeline/formatter.py
  -> api/v1/mappers.py
```

## Directory Roles

```text
app/api/v1/        FastAPI schemas, routes, HTTP/domain mappers
app/application/   QueryService, ReportService, service catalog
app/domain/        evidence, task, and report dataclasses
app/pipeline/      Orchestrator, Retriever, Analyzer, Critic, Formatter
app/integrations/  OpenDota, patch notes, STRATZ client
app/data/          fixtures and patch JSON
app/llm/           LLM provider and prompt loader
app/core/          settings
```

## Current Endpoints

```text
GET  /health
GET  /api/v1/services
POST /api/v1/query
POST /api/v1/meta-report
POST /api/v1/patch-impact
POST /api/v1/team-report
POST /api/v1/verify-claim
```

`/api/v1/query/experimental` has been removed. The frontend `AskConsole` now calls `/api/v1/query`.

## Data Strategy

External live data is disabled by default so tests and local development do not block on OpenDota network calls.

```text
METAMIND_LIVE_DATA_ENABLED=false  # default
METAMIND_LIVE_DATA_ENABLED=true   # explicitly enable OpenDota live retrieval
```

Patch impact still reads local `apps/api/app/data/patches/7_41d.json`.

## LLM Status

LLM remains optional. `AnalyzerAgent` generates meta hero `reasons` and `practice_advice` only when `METAMIND_LLM_ENABLED=true` and the provider is available. Orchestrator and Critic are currently rule-based, but their boundaries now live in `pipeline/` and can be upgraded to LLM function calling / LLM critic later.

## Verification Status

Passed:

```bash
cd apps/api && python -m pytest
cd apps/api && python -m ruff check app tests
npm run typecheck --workspace apps/web
```

Latest result: backend `16 passed, 3 skipped`, backend lint passed, frontend TypeScript typecheck passed.
