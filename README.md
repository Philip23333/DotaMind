# MetaMind

MetaMind is a composable esports intelligence agent that turns Dota2 patch notes, match data, and pro team statistics into evidence-grounded answers and verifiable game meta reports.

This repository is in active development. The legacy report pipeline still exists for `/api/v1/query` and report endpoints, while the new `/api/v1/plan` path is moving toward the v2.5/v3 agentic architecture: Planner -> Tools -> EvidenceGraph -> Answer -> Critic -> Response.

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
Use `http://localhost:8001/debug/chat` for the legacy query console and `http://localhost:8001/debug/plan` for the agentic plan console.

### Frontend

```bash
npm install
npm run dev:web
```

Open `http://localhost:3000`.

The frontend is deprecated. For internal testing, prefer the FastAPI debug pages above.

### Optional Services

```bash
docker compose up -d
```

This starts PostgreSQL and Redis for later persistence, caching, and job orchestration work.

## Pipeline Workflow

The backend currently has two execution paths.

Legacy report path:

```text
HTTP / CAP / A2A caller
  -> application use case
  -> Orchestrator Agent
  -> Retriever tool
  -> Analyzer Agent
  -> Critic Agent
  -> Formatter tool
```

Agentic plan path:

```text
POST /api/v1/plan
  -> AgenticPlanner
  -> validate_plan_node
  -> tool_executor_node
  -> evidence_node
  -> answer_node
     -> StructuredReportSynthesizer
     -> NaturalLanguageAnswerSynthesizer
  -> critic_node
  -> response_node
```

The agentic path does not fallback to the legacy pipeline. Missing tools, validation errors, and tool execution failures are surfaced directly.

Allowed agentic `output_contract` values:

- `patch_impact_report`
- `role_meta_report`
- `team_recent_report`
- `hero_matchup_report`
- `draft_advice`
- `natural_language_answer`

`meta_list` means the internal whitelist of structured output contracts. It is not a valid `output_contract`; free-form supported questions should use `natural_language_answer`.

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

```bash
curl -X POST http://localhost:8001/api/v1/plan \
  -H "Content-Type: application/json" \
  -d "{\"game\":\"dota2\",\"query\":\"enemy picked Lina, what should I pick?\"}"
```

Callable services are listed at:

```bash
curl http://localhost:8001/api/v1/services
```

## Data Sources

Current and planned data sources:

- OpenDota API for public and pro match data.
- STRATZ GraphQL API for higher-granularity hero, draft, and trend signals.
- Local curated Dota2 patch JSON under `apps/api/app/data/patches/`.
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
- Experimental `/api/v1/plan` agentic path with node-style execution.
- Agentic tools for hero resolution, STRATZ matchup/lane outcome, OpenDota team/meta evidence, and local patch records.
- EvidenceGraph, structured answer synthesis, natural-language answer synthesis, and agentic critic.
- Optional LLM function calling for orchestration and optional hero insight generation.
- OpenDota live retrieval for hero and team reports when enabled.
- Deterministic team resolution with ambiguous-candidate selection through `/debug/chat`.
- `/debug/plan` page for inspecting node flow, plan, tool results, evidence, answer, and review.
- Unified business policy in `apps/api/app/config/policy.yaml`.
- Unit tests and Ruff checks for backend services.

Next:

- Continue migrating legacy report capabilities into agentic tools and answer contracts.
- Improve structured report quality for team, role meta, patch impact, and hero matchup outputs.
- Add more draft evidence tools such as hero synergy, counters by role, and lane context.
- Move the node-style implementation to LangGraph when graph boundaries stabilize.
- Implement CAP order verification and settlement callbacks.

## License

MIT. See `LICENSE`.
