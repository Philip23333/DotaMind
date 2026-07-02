# MetaMind

MetaMind is a composable esports intelligence agent that turns Dota 2 patch
notes, match data, and pro team statistics into evidence-grounded answers.

This repository is in active development. The old fixed report pipeline and its
public endpoints have been removed. The backend now exposes the v2.5/v3 agentic
path as the single API workflow:

```text
Planner -> validated tools -> EvidenceGraph -> Answer -> Critic -> Response
```

## Repository Layout

```text
apps/
  api/        FastAPI service, LangGraph-backed agentic workflow, integrations, tests
  web/        Deprecated Next.js dashboard; do not modify unless explicitly needed
docs/         Architecture, API, configuration, and CAP integration notes
```

## Run Locally

```bash
cd apps/api
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 --log-level info
```

Or run `npm run dev:api` from the repository root. The startup script uses fixed
port `8001` and fails if the port is already occupied.

Open:

- `http://localhost:8001/docs`
- `http://localhost:8001/debug/plan`

The frontend under `apps/web` is deprecated. Use `/debug/plan` as the internal
query test UI.

## Current API

```bash
curl -X POST http://localhost:8001/api/v1/plan \
  -H "Content-Type: application/json" \
  -d "{\"game\":\"dota2\",\"query\":\"enemy picked Lina, what should I pick?\"}"
```

Removed endpoints are intentionally not redirected or wrapped:

- `POST /api/v1/query`
- `POST /api/v1/meta-report`
- `POST /api/v1/patch-impact`
- `POST /api/v1/team-report`
- `POST /api/v1/verify-claim`
- `GET /api/v1/services`
- `GET /debug/chat`

## Agentic Workflow

`POST /api/v1/plan` runs a LangGraph `StateGraph(AgentRunState)`:

```text
planner_node
  -> validate_plan_node
  -> tool_executor_node
  -> evidence_node
  -> answer_node
  -> critic_node
  -> response_node
```

Missing tools, validation errors, tool failures, and insufficient evidence are
returned directly. There is no fallback to the old report pipeline.

Allowed `output_contract` values:

- `patch_impact_report`
- `role_meta_report`
- `team_recent_report`
- `hero_matchup_report`
- `draft_advice`
- `natural_language_answer`

Registered agentic tools include hero resolution, STRATZ pair-lane / matchup-ranking / lane-meta / position-stats tools, OpenDota team/meta evidence, and local patch records.

## Configuration

Runtime environment, secrets, URLs, and feature flags live in `.env`. Business
policy lives in `apps/api/app/config/policy.yaml` and is validated on startup.

```text
METAMIND_LIVE_DATA_ENABLED=false
METAMIND_LLM_ENABLED=false
METAMIND_LLM_API_KEY=
METAMIND_POLICY_PATH=
```

`policy.yaml` controls OpenDota transport settings, team resolution and
sampling, hero scoring and evidence thresholds, patch scoring, Critic rules, and
LLM call parameters. Restart the API after editing it.

## Data Sources

- OpenDota API for public and pro match data.
- STRATZ GraphQL API for higher-granularity hero, draft, and trend signals.
- Local curated Dota 2 patch JSON under `apps/api/app/data/patches/`.

## Current Status

Implemented:

- FastAPI app and OpenAPI schema for `/api/v1/plan`.
- LangGraph-backed agentic runtime.
- Tool registry, tool executor, EvidenceGraph, answer synthesis, and critic.
- `/debug/plan` page for inspecting plan, tool results, evidence, answer, review,
  and trace.
- Unit tests and Ruff checks for the backend.

Next:

- Add `hero.enrich_identity`, role filtering, patch context, synergy evidence,
  and ranking tools.
- Improve evidence-kind-specific quality rules.
- Design a CAP surface around agentic output contracts instead of old fixed
  report services.

## License

MIT. See `LICENSE`.
