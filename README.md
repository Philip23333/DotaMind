# DotaMind

DotaMind is an evidence-grounded Dota 2 intelligence agent. It plans constrained
tool calls, retrieves structured data, builds an `EvidenceGraph`, synthesizes an
answer, and runs a rule-first critic before returning a response.

This repository is in active development. The old fixed report pipeline and its
public endpoints have been removed. The implemented product capabilities are
described by V3.0, while the V3.2 target freezes tool expansion to strengthen the
Agent Runtime Foundation. Both preserve the v2.5 constrained Tool Calling
architecture:

```text
Planner -> Validate -> Tools -> Evidence -> Answer -> Critic -> Response
```

Start with the [documentation index](docs/README.md), then read the
[DotaMind V3.2 runtime design](docs/design/versions/DotaMind_V3.2_design.md), the
[V3.2-1 implementation blueprint](docs/design/versions/DotaMind_V3.2-1_design.md),
the [DotaMind V3.0 capability design](docs/design/versions/DotaMind_V3.0_design.md),
and the [v2.5 architecture foundation](docs/design/versions/DotaMind_MVP_v2.5.md).

## Repository Layout

```text
apps/
  api/        FastAPI service, agentic workflow, tests, and `/debug/plan` UI
  chat/       assistant-ui client for the public `/api/v1/plan` conversation path
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
second terminal, start the minimal chat client:

```bash
cd apps/chat
npm install
npm run dev
```

Useful local pages:

- `http://localhost:8001/docs`
- `http://localhost:8001/debug/plan`
- `http://localhost:3000` for the assistant-ui chat client

The chat client calls only `POST /api/v1/plan`; it does not host a model or a
parallel Agent Runtime. Use `/debug/plan` for internal plan/runtime inspection.

## Current API

```bash
curl -X POST http://localhost:8001/api/v1/plan \
  -H "Content-Type: application/json" \
  -d '{"game":"dota2","query":"enemy picked Lina, what should I pick?"}'
```

Active endpoints:

- `GET /health`
- `POST /api/v1/plan`
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

Current output contracts:

- `natural_language_answer`
- `patch_impact_report`
- `role_meta_report`
- `team_recent_report`

The current registry exposes 19 deterministic tools across local hero constants,
STRATZ hero/player analysis, OpenDota team/role data, and local patch records.
See the [V3 tool inventory](docs/design/versions/DotaMind_V3.0_design.md#8-当前工具列表)
for the complete list.

## Configuration

Runtime environment, secrets, URLs, and feature flags live in `.env`. Business
policy lives in `apps/api/app/config/policy.yaml` and is validated on startup.

```text
DOTAMIND_LIVE_DATA_ENABLED=false
DOTAMIND_STRATZ_TOKEN=
DOTAMIND_LLM_ENABLED=false
DOTAMIND_LLM_API_KEY=
DOTAMIND_POLICY_PATH=
```

The policy covers OpenDota and STRATZ transport boundaries, team/hero/patch
report rules, critic quality gates, LLM call settings, and planner sample policy.
Restart the API after editing it.

## Current V3 Focus

Completed capability slices include hero matchup, synergy, position filtering,
daily trends, player profile/recent-performance queries, team reports, and patch
records.

The active V3.2 architecture-stabilization target freezes new business tools
while adding run/attempt state, bounded recovery, request idempotency, Redis
session persistence, Prompt Registry, and observability. See the
[V3.2 design](docs/design/versions/DotaMind_V3.2_design.md). Product capability gaps such
as item/skill/talent guidance remain documented but are deferred until the
runtime foundation is complete. CAP/CROO integration remains parked.

## Deploy with Docker Compose

The production Compose stack runs PostgreSQL, Redis, FastAPI, Next.js, and an
Nginx reverse proxy. Only Nginx port `80` is published; the application and data
services remain on the internal Docker network.

1. Copy the repository and a populated `.env` file to the server.
2. Set `DOTAMIND_PUBLIC_ORIGIN` to the public HTTP origin when it differs from
   the current Tencent Cloud target. Set `DOTAMIND_POSTGRES_PASSWORD` to replace
   the internal single-node default before using the stack for durable data.
3. Build and start the stack:

   ```bash
   docker compose -f compose.prod.yml up -d --build
   ```

4. Verify the public entry points and container state:

   ```bash
   curl http://<server-ip>/health
   docker compose -f compose.prod.yml ps
   docker compose -f compose.prod.yml logs --tail=100 api chat nginx
   ```

The API container runs `alembic upgrade head` before starting Uvicorn. The chat
build uses a relative API URL, so Nginx keeps browser and API requests on the
same origin. `apps/api/requirements.prod.txt` is generated from `uv.lock`; after
changing API dependencies, regenerate it with:

```bash
cd apps/api
uv export --frozen --no-dev --no-emit-project --no-hashes \
  --output-file requirements.prod.txt
```

The current stack provides HTTP only. Add a domain and TLS termination before
treating it as an Internet-facing production service.

## License

MIT. See `LICENSE`.
