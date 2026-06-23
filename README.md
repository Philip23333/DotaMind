# MetaMind

MetaMind is a composable esports intelligence agent that turns Dota2 patch notes, match data, and pro team statistics into verifiable, paid game meta reports for humans and other agents.

This repository is the MetaMind MVP implementation based on the canonical v2.1 pipeline. It supports mock-backed local development and optional OpenDota live retrieval while keeping API contracts, agent boundaries, and the CAP/A2A service shape stable.

## What It Solves

Existing Dota2 data products answer where the data is. MetaMind answers what the data means, why a conclusion is supported, and how another agent can call that conclusion as a paid service.

Core MVP reports:

- Meta report: ranked hero recommendations by role and patch.
- Patch impact report: winners, losers, item impact, lineup trends.
- Team intelligence report: recent form, draft preferences, patch adaptation.
- Claim verification: evidence check for game meta claims.

## Repository Layout

```text
apps/
  api/        FastAPI service, canonical pipeline, integrations, tests
  web/        Deprecated Next.js dashboard; do not modify unless explicitly needed
docs/         Architecture, API, configuration, and CAP integration notes
PRODUCT.md   Product strategy context for design and agent work
DESIGN.md    Visual system notes and CSS token source
```

## Run Locally

### Backend

```bash
cd apps/api
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 --log-level info
```

Or run `npm run dev:api` from the repository root. The startup script uses fixed port `8001` and fails if the port is already occupied.

Open `http://localhost:8001/docs` for the FastAPI schema.

### Frontend

```bash
npm install
npm run dev:web
```

Open `http://localhost:3000`.

The frontend falls back to local mock data if the API is not running.
For internal query testing, prefer the FastAPI page at `http://localhost:8001/debug/chat`.

### Optional Services

```bash
docker compose up -d
```

This starts PostgreSQL and Redis for later persistence, caching, and job orchestration work.

## Pipeline Workflow

The backend keeps one canonical execution path:

```text
HTTP / CAP / A2A caller
  -> application use case
  -> Orchestrator Agent
  -> Retriever tool
  -> Analyzer Agent
  -> Critic Agent
  -> Formatter tool
```

Only LLM decision boundaries are treated as Agents. Deterministic fetching and rendering remain tools. Structured endpoints and natural-language `/api/v1/query` both use this same pipeline.

## Configuration

Runtime environment, secrets, URLs, and feature flags live in `.env`. Business policy lives in `apps/api/app/config/policy.yaml` and is validated on startup.

```text
METAMIND_LIVE_DATA_ENABLED=false
METAMIND_LLM_ENABLED=false
METAMIND_LLM_API_KEY=
METAMIND_POLICY_PATH=
```

`policy.yaml` controls OpenDota transport settings, team resolution and sampling, hero scoring and evidence thresholds, patch scoring, Critic rules, and LLM call parameters. Policy is cached for the process lifetime, so restart the API after editing it.

## API Examples

```bash
curl -X POST http://localhost:8001/api/v1/meta-report \
  -H "Content-Type: application/json" \
  -d "{\"game\":\"dota2\",\"patch\":\"latest\",\"role\":\"offlane\"}"
```

```bash
curl -X POST http://localhost:8001/api/v1/verify-claim \
  -H "Content-Type: application/json" \
  -d "{\"game\":\"dota2\",\"claim\":\"Beastmaster is one of the strongest offlaners in current patch.\"}"
```

Callable services are listed at:

```bash
curl http://localhost:8001/api/v1/services
```

## Data Sources

Planned production data sources:

- OpenDota API for public and pro match data.
- STRATZ GraphQL API for higher-granularity hero, draft, and trend signals.
- Official Dota2 Patch Notes for patch extraction.
- Liquipedia as an optional team and tournament context source.

## CAP / Commerce Shape

The MVP exposes service descriptors with prices:

- `get_meta_report`: 0.1 USDC
- `get_team_report`: 0.3 USDC
- `get_patch_impact`: 0.5 USDC
- `verify_meta_claim`: 0.05 USDC placeholder

See `docs/technical/cap-integration.md` for the planned order, payment, callback, and audit-log flow.

## Current Status

Implemented:

- FastAPI app and OpenAPI schema.
- Canonical `Orchestrator -> Retriever -> Analyzer -> Critic -> Formatter` pipeline.
- Natural-language `/api/v1/query` and structured report endpoints.
- Optional LLM function calling for orchestration and optional hero insight generation.
- OpenDota live retrieval for hero and team reports when enabled.
- Deterministic team resolution with ambiguous-candidate selection through `/debug/chat`.
- Unified business policy in `apps/api/app/config/policy.yaml`.
- Unit tests and Ruff checks for backend services.

Next:

- Move long-lived OpenDota match-detail cache to Redis or another persistent cache.
- Add partial-data degradation for upstream OpenDota failures.
- Add path-level OpenDota success-rate, P50/P95, and cache-hit metrics.
- Add STRATZ GraphQL draft presence integration.
- Persist report runs and verification evidence.
- Implement CAP order verification and settlement callbacks.

## License

MIT. See `LICENSE`.
