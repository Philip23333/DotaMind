# DotaMind

DotaMind is an evidence-grounded Dota 2 intelligence agent. It plans constrained
tool calls, retrieves structured data, builds an `EvidenceGraph`, synthesizes an
answer, and runs a rule-first critic before returning a response.

This repository is in active development. The old fixed report pipeline and its
public endpoints have been removed. V3.2 completed the bounded Agent Runtime
Foundation; V3.3 added durable PostgreSQL Chat Runs and the committed Valve
Catalog. All current work preserves the v2.5 constrained Tool Calling boundary:

```text
Controller -> Decision Validation -> Tools -> Evidence -> Answer -> Critic -> Response
```

Start with the [documentation index](docs/README.md), the current
[technical architecture](docs/technical/architecture.md), and the
[v2.5 architecture foundation](docs/design/versions/DotaMind_MVP_v2.5.md).
Version blueprints are retained as implementation history; the latest progress
snapshot and current code decide implementation status.

## Repository Layout

```text
apps/
  api/        FastAPI service, agentic workflow, tests, and `/debug/plan` UI
  chat/       Next.js/assistant-ui client for Chat Session and Chat Run APIs
docs/
  design/     Version blueprints, architecture, tool designs, and roadmaps
  technical/  API, configuration, and provider reference material
  progress/   Daily cumulative bilingual handoff snapshots
  archive/    Superseded product and architecture documents
```

## Run Locally

```bash
cd apps/api
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 --log-level info
```

The API uses port `8001` and fails when the port is already occupied. In a
second terminal, start the chat client:

```bash
cd apps/chat
npm install
npm run dev
```

Useful local pages:

- `http://localhost:8001/docs`
- `http://localhost:8001/debug/plan`
- `http://localhost:3000` for the assistant-ui chat client

The chat client uses the PostgreSQL-backed Chat Session and detached Chat Run
APIs; it does not host a model or parallel Agent Runtime. `/debug/plan` remains
the internal plan/runtime inspection UI.

## Current API

```bash
curl -X POST http://localhost:8001/api/v1/plan \
  -H "Content-Type: application/json" \
  -d '{"game":"dota2","query":"enemy picked Lina, what should I pick?"}'
```

Active endpoints:

- `GET /health`
- `POST /api/v1/plan`
- `POST /api/v1/plan/stream`
- `/api/v1/chat/sessions` session CRUD
- `/api/v1/chat/.../runs` create/query/active/events/cancel
- `GET /debug/plan`

Removed endpoints are intentionally not redirected or wrapped:

- `POST /api/v1/query`
- `POST /api/v1/meta-report`
- `POST /api/v1/patch-impact`
- `POST /api/v1/team-report`
- `POST /api/v1/verify-claim`
- `GET /api/v1/services`
- `GET /debug/chat`

## Agentic Runtime

Both stateless debug requests and durable Chat Runs execute the same LangGraph
`StateGraph(AgentRunState)`:

```text
controller_node
  -> decision_validate_node
      -> direct_answer / clarification / context_missing / capability_boundary
      -> tool_plan -> validate_plan_node -> tool_executor_node
                   -> conversation.history_lookup -> controller_node
                   -> evidence_node -> answer_node -> critic_node
  -> attempt_finalize_node -> recovery_node -> run_finalize_node -> response_node
```

Missing tools, validation errors, tool failures, and insufficient evidence are
returned directly. There is no fallback to the old report pipeline.

Current output contracts:

- `natural_language_answer`
- `patch_impact_report`
- `role_meta_report`
- `team_recent_report`

The current registry exposes 30 deterministic tools across the committed Valve
Catalog, STRATZ hero/player analysis, PandaScore Dota 2 Fixture schedules and
identity resolution, OpenDota team/role and single-match data, local patch
records, and request-local conversation history lookup. Registry definitions,
not a copied documentation list, are authoritative.

## Configuration

Runtime environment, secrets, URLs, and feature flags live in `.env`. Business
policy lives in `apps/api/app/config/policy.yaml` and is validated on startup.

```text
DOTAMIND_LIVE_DATA_ENABLED=false
DOTAMIND_PANDASCORE_TOKEN=
DOTAMIND_PANDASCORE_BASE_URL=https://api.pandascore.co
DOTAMIND_STRATZ_TOKEN=
DOTAMIND_LLM_ENABLED=false
DOTAMIND_LLM_API_KEY=
DOTAMIND_POLICY_PATH=
```

The policy covers OpenDota, PandaScore, and STRATZ transport boundaries,
team/hero/patch report rules, critic quality gates, LLM call settings, planner
sample policy, and conversation memory budgets. The free PandaScore Fixture
boundary does not infer Valve match IDs from PandaScore IDs.
Restart the API after editing it.

## Current Architecture

The current backend includes bounded Run/Attempt/Budget execution, one bounded
missing-evidence replan, PostgreSQL-authoritative Chat Runs, a Redis recent
dialogue cache and event/coordinator boundary, history-grounded answers, and six
official Catalog tools for hero, ability, talent, and item facts. It does not
maintain a discourse graph or use LangGraph checkpointing for conversation
memory. CAP/CROO integration remains parked.

## Deploy with Docker Compose

The production Compose stack runs PostgreSQL, Redis, FastAPI, Next.js, and an
Nginx reverse proxy. Only Nginx port `80` is published; application and data
services remain on the internal Docker network.

```bash
docker compose -f compose.prod.yml up -d --build
curl http://<server-ip>/health
docker compose -f compose.prod.yml ps
```

The API container runs `alembic upgrade head` before Uvicorn. Configure
`DOTAMIND_PUBLIC_ORIGIN` and replace the default PostgreSQL password before a
durable deployment. The current stack provides HTTP only; add a domain and TLS
termination before exposing it to the Internet.

## License

MIT. See `LICENSE`.
