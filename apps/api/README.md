# MetaMind API

FastAPI backend for the MetaMind MVP.

The backend currently has two paths:

- `/api/v1/query`: legacy report pipeline.
- `/api/v1/plan`: experimental agentic planner path with node-style execution.

## Run

```bash
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 --log-level info
```

From the repository root, `npm run dev:api` runs `dev-api.cmd`, which uses fixed port `8001` and exits with an error when the port is already occupied.

Useful local pages:

- `http://localhost:8001/docs`
- `http://localhost:8001/debug/chat`
- `http://localhost:8001/debug/plan`

## Query Smoke Runner

With the API running on `127.0.0.1:8001`, run:

```bash
python scripts/query_smoke.py
```

The runner calls `/api/v1/query` with representative natural-language prompts and prints the
HTTP status, route, Critic quality-gate status, key report fields, sources, and elapsed time.
Use `--base-url` to target a different local API instance.

## Agentic Plan Debug

With the API running on `127.0.0.1:8001`, test the live planner route:

```bash
curl -X POST http://localhost:8001/api/v1/plan \
  -H "Content-Type: application/json" \
  -d "{\"game\":\"dota2\",\"query\":\"enemy picked Lina, what should I pick?\"}"
```

Or use the local debug page:

```text
http://localhost:8001/debug/plan
```

The response includes:

- `plan`
- `tool_results`
- `evidence_graph`
- `answer`
- `review`
- `trace`

The agentic path does not fallback to the legacy report pipeline. Missing tools,
planner validation errors, and tool execution errors are returned directly.

## Endpoints

- `GET /health`
- `GET /api/v1/services`
- `POST /api/v1/meta-report`
- `POST /api/v1/patch-impact`
- `POST /api/v1/team-report`
- `POST /api/v1/verify-claim`
- `POST /api/v1/query`
- `POST /api/v1/plan`

## Agentic Path

Current node flow:

```text
AgenticPlanner
  -> validate_plan_node
  -> tool_executor_node
  -> evidence_node
  -> answer_node
     -> StructuredReportSynthesizer
     -> NaturalLanguageAnswerSynthesizer
  -> critic_node
  -> response_node
```

Allowed `output_contract` values:

- `patch_impact_report`
- `role_meta_report`
- `team_recent_report`
- `hero_matchup_report`
- `draft_advice`
- `natural_language_answer`

`meta_list` is the internal whitelist of structured output contracts. It is not
a valid `output_contract`. If a supported question does not fit one of the
structured contracts, the planner should use `natural_language_answer`.

Registered agentic tools:

- `resolve_hero`
- `stratz.hero_vs_hero_matchup`
- `stratz.lane_outcome`
- `opendota.resolve_team`
- `opendota.team_recent_matches`
- `opendota.team_players`
- `opendota.team_heroes`
- `opendota.hero_stats_by_role`
- `patch.get_records`
- `patch.hero_changes`
- `patch.item_changes`

## Configuration

Secrets, environment-specific URLs, and feature flags are loaded from `.env`. Business policy
is loaded from `app/config/policy.yaml` and validated by Pydantic at startup.

```text
METAMIND_OPENDOTA_API_KEY=...
METAMIND_LIVE_DATA_ENABLED=true
METAMIND_LLM_ENABLED=true
METAMIND_LLM_API_KEY=...
METAMIND_LLM_BASE_URL=https://api.deepseek.com
METAMIND_LLM_MODEL=deepseek-chat
METAMIND_POLICY_PATH=C:/optional/absolute/path/to/policy.yaml
```

`policy.yaml` is the single source for OpenDota transport settings, team resolution and sampling,
hero scoring and evidence thresholds, patch scoring, Critic rules, and LLM call parameters.
Patch facts remain under `app/data/patches/`, and prompt text remains under
`app/resources/prompts/`.

Policy is cached for the process lifetime. Restart the API after changing `policy.yaml` or an override file pointed to by `METAMIND_POLICY_PATH`.
