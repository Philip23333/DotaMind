# MetaMind

MetaMind is a composable esports intelligence agent that turns Dota2 patch notes, match data, and pro team statistics into verifiable, paid game meta reports for humans and other agents.

This repository is the MVP skeleton based on `MetaMind_MVP.md`. It starts with mock data so the web dashboard, API contracts, agent workflow, and CAP/A2A service shape can be developed before live OpenDota, STRATZ, and patch-note ingestion are fully connected.

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
  api/        FastAPI service, agent layers, services, integrations, tests
  web/        Next.js dashboard with Tailwind and ECharts
docs/         Architecture, API, and CAP integration notes
PRODUCT.md   Product strategy context for design and agent work
DESIGN.md    Visual system notes and CSS token source
```

## Run Locally

### Backend

```bash
cd apps/api
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/docs` for the FastAPI schema.

### Frontend

```bash
npm install
npm run dev:web
```

Open `http://localhost:3000`.

The frontend falls back to local mock data if the API is not running.

### Optional Services

```bash
docker compose up -d
```

This starts PostgreSQL and Redis for later persistence, caching, and job orchestration work.

## Agent Workflow

The backend keeps the MVP workflow explicit:

```text
Planner Agent
-> Data Agent
-> Patch Agent
-> Meta Reasoning Agent
-> Verification Agent
-> Report Agent
```

The current services use fixtures behind this contract. Live integrations can replace the fixture layer without changing the HTTP response models or frontend components.

## API Examples

```bash
curl -X POST http://localhost:8000/api/v1/meta-report \
  -H "Content-Type: application/json" \
  -d "{\"game\":\"dota2\",\"patch\":\"latest\",\"role\":\"offlane\"}"
```

```bash
curl -X POST http://localhost:8000/api/v1/verify-claim \
  -H "Content-Type: application/json" \
  -d "{\"game\":\"dota2\",\"claim\":\"Beastmaster is one of the strongest offlaners in current patch.\"}"
```

Callable services are listed at:

```bash
curl http://localhost:8000/api/v1/services
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

See `docs/cap-integration.md` for the planned order, payment, callback, and audit-log flow.

## Current Status

Implemented:

- FastAPI app and OpenAPI schema.
- Agent and service modules for the MVP report workflow.
- Mock-backed response contracts for all four core services.
- Next.js dashboard wired to the API with mock fallback.
- ECharts score visualization and CAP service catalog panel.
- Unit tests for backend services.

Next:

- Replace fixtures with OpenDota live data.
- Add patch-note ingestion and structured change extraction.
- Add STRATZ GraphQL draft presence integration.
- Persist report runs and verification evidence.
- Implement CAP order verification and settlement callbacks.

## License

MIT. See `LICENSE`.
