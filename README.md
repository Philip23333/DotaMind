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

The API uses port `8001` and fails when the port is already occupied.

Useful local pages:

- `http://localhost:8001/docs`
- `http://localhost:8001/debug/plan`

There is no separate frontend application. Use `/debug/plan` as the internal
query test UI.

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

## License

MIT. See `LICENSE`.
