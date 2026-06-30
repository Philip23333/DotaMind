# MetaMind API

FastAPI backend for the MetaMind agentic workflow.

The old fixed report/query pipeline has been removed. The current API surface is:

- `GET /health`
- `POST /api/v1/plan`
- `GET /debug/plan`

## Run

```bash
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 --log-level info
```

From the repository root, `npm run dev:api` runs `dev-api.cmd`, which uses fixed
port `8001` and exits with an error when the port is already occupied.

Useful local pages:

- `http://localhost:8001/docs`
- `http://localhost:8001/debug/plan`

## Agentic Plan Debug

With the API running on `127.0.0.1:8001`, test the planner route:

```bash
curl -X POST http://localhost:8001/api/v1/plan \
  -H "Content-Type: application/json" \
  -d "{\"game\":\"dota2\",\"query\":\"enemy picked Lina, what should I pick?\"}"
```

The response includes:

- `plan`
- `tool_results`
- `evidence_graph`
- `answer`
- `review`
- `trace`

Missing tools, planner validation errors, and tool execution errors are returned
directly. There is no compatibility fallback to old report endpoints.

## Agentic Path

Current LangGraph node flow:

```text
planner_node
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

Secrets, environment-specific URLs, and feature flags are loaded from `.env`.
Business policy is loaded from `app/config/policy.yaml` and validated by
Pydantic at startup.

```text
METAMIND_OPENDOTA_API_KEY=...
METAMIND_LIVE_DATA_ENABLED=true
METAMIND_LLM_ENABLED=true
METAMIND_LLM_API_KEY=...
METAMIND_LLM_BASE_URL=https://api.deepseek.com
METAMIND_LLM_MODEL=deepseek-chat
METAMIND_POLICY_PATH=C:/optional/absolute/path/to/policy.yaml
```

Policy is cached for the process lifetime. Restart the API after changing
`policy.yaml` or an override file pointed to by `METAMIND_POLICY_PATH`.
