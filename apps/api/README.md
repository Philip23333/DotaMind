# DotaMind API

FastAPI backend for the DotaMind V3 agentic workflow.

The old fixed report/query pipeline has been removed. The current API surface is:

- `GET /health`
- `POST /api/v1/plan`
- `GET /debug/plan`

## Run

```bash
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 --log-level info
```

From the repository root, `npm run dev:api` runs `dev-api.cmd`, which uses port
`8001` and exits when the port is already occupied.

Useful local pages:

- `http://localhost:8001/docs`
- `http://localhost:8001/debug/plan`

## Agentic Plan

```bash
curl -X POST http://localhost:8001/api/v1/plan \
  -H "Content-Type: application/json" \
  -d '{"game":"dota2","query":"enemy picked Lina, what should I pick?"}'
```

The response exposes the plan, tool results, evidence graph, answer, review,
errors, trace, and planner debugging metadata. Missing tools, invalid plans,
upstream errors, and insufficient evidence are returned directly.

Current LangGraph path:

```text
planner_node
  -> validate_plan_node
  -> tool_executor_node
  -> evidence_node
  -> answer_node
  -> critic_node
  -> response_node
```

## Output Contracts

- `natural_language_answer`
- `patch_impact_report`
- `role_meta_report`
- `team_recent_report`

The contract registry in `app/agentic/planning/contracts.py` is authoritative.

## Registered Tools

Local hero constants and STRATZ:

- `resolve_hero`
- `stratz.pair_lane_outcome`
- `stratz.hero_matchup_ranking`
- `stratz.hero_synergy_ranking`
- `stratz.lane_meta_global`
- `stratz.hero_position_stats`
- `stratz.hero_daily_trends`
- `stratz.filter_heroes_by_position`
- `stratz.player_profile`
- `stratz.player_recent_matches`
- `stratz.player_hero_performance`

OpenDota:

- `opendota.resolve_team`
- `opendota.team_recent_matches`
- `opendota.team_players`
- `opendota.team_heroes`
- `opendota.hero_stats_by_role`

Local patch records:

- `patch.get_records`
- `patch.hero_changes`
- `patch.item_changes`

The `ToolRegistry` definitions are authoritative for arguments, output paths,
reference contracts, and evidence kinds.

## Configuration

Secrets, environment-specific URLs, and feature flags are loaded from `.env`.
Business policy is loaded from `app/config/policy.yaml` and validated by
Pydantic at startup.

```text
METAMIND_LIVE_DATA_ENABLED=false
METAMIND_OPENDOTA_API_KEY=
METAMIND_STRATZ_TOKEN=
METAMIND_LLM_ENABLED=false
METAMIND_LLM_PROVIDER=deepseek
METAMIND_LLM_API_KEY=
METAMIND_LLM_BASE_URL=https://api.deepseek.com
METAMIND_LLM_MODEL=deepseek-chat
METAMIND_POLICY_PATH=
```

Policy is cached for the process lifetime. Restart the API after changing
`policy.yaml` or an override file.

See the repository [documentation index](../../docs/README.md) and
[configuration reference](../../docs/technical/configuration.md) for details.
