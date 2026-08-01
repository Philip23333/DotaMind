# DotaMind API

FastAPI backend for the DotaMind V3 agentic workflow.

The old fixed report/query pipeline has been removed. The current API surface is:

- `GET /health`
- `POST /api/v1/plan`
- `GET /debug/plan`

## Run

Python 3.10+ is required. The recommended local workflow uses
[`uv`](https://docs.astral.sh/uv/), so the API does not depend on whichever
global Python or Conda environment happens to be active.

From the repository root:

```bash
uv sync --project apps/api --extra dev
uv run --project apps/api uvicorn app.main:app --app-dir apps/api --reload --host 127.0.0.1 --port 8001 --log-level info
```

From `apps/api`:

```bash
uv sync --extra dev
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 --log-level info
```

On Windows, `npm run dev:api` from the repository root runs `dev-api.cmd`,
which executes the same `uv`-managed application on port `8001` and exits when
the port is already occupied.

If `uv` is not available, install into and run from the **same** Python
interpreter:

```bash
cd apps/api
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 --log-level info
```

`No module named uvicorn` means the selected interpreter has not completed the
install step. Check it with `python -c "import sys; print(sys.executable)"`; do
not assume an activated Conda environment contains the project dependencies.

Useful local pages:

- `http://localhost:8001/docs`
- `http://localhost:8001/debug/plan`

## Agentic Plan

```bash
curl -X POST http://localhost:8001/api/v1/plan \
  -H "Content-Type: application/json" \
  -d '{"game":"dota2","query":"enemy picked Lina, what should I pick?"}'
```

The response exposes the Controller decision kind and, when applicable, the
final plan, effective evidence obligations, tool results, evidence graph,
answer, review, errors and trace. Conversation recall, clarification, missing
context and capability boundaries skip the tool/evidence/critic path.

## Multi-turn Sessions

`POST /api/v1/plan` accepts an optional `session_id` (UUID v4). It is opt-in:

- Omit it (or send `null`) for stateless single-turn behaviour. This is the
  default, except the response always carries a `"session_id": null` field and
  the Controller prompt includes a short
  history-usage rule block even when no history exists.
- Send a client-generated UUID v4 to enable session memory. The service reads
  the most recent turns (see `conversation.history_window` in `policy.yaml`),
  injects a compact summary into the Controller prompt so it can resolve pronouns
  ("那他出什么装") and inherit scope, then stores a summary of the new turn.

```bash
# Client generates and reuses the same UUID across turns.
SID=$(python -c "import uuid; print(uuid.uuid4())")
curl -s -X POST http://localhost:8001/api/v1/plan \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"对手选了 Lina 我选什么克制\",\"session_id\":\"$SID\"}"
curl -s -X POST http://localhost:8001/api/v1/plan \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"那他适合走几号位\",\"session_id\":\"$SID\"}"
```

Notes and SessionStore limits:

- History is injected as *untrusted context* only, not evidence. Each turn
  confirms hero/team/player identity through the current plan before a
  downstream data tool can use its ID. Stateful responses never expose Controller
  prompts or raw Controller output; stateful Controller failures return a stable,
  redacted error envelope.
- `DOTAMIND_SESSION_STORE_BACKEND=memory` is the default for local development.
  `DOTAMIND_SESSION_STORE_BACKEND=redis` requires `DOTAMIND_REDIS_URL` and shares
  sessions across workers. Redis startup failure stops the API; runtime failure returns
  `session_store_error` and never falls back to memory. Redis retains compact Turns and
  allowlisted completed responses, not prompts, raw model output, history render blocks or secrets.
  API/worker rebuild recovery requires the same Redis data; Redis Server restart durability requires
  AOF/RDB plus a persistent volume. Active or waiting in-memory sessions are never evicted;
  `max_sessions` can be temporarily exceeded while every candidate is active. The `/debug/plan` console has a
  `session_id` field with a "新建会话" button for manual multi-turn testing.

Current conditional LangGraph path:

```text
controller_node
  -> decision_validate_node
      -> direct_answer -> conversation_answer_node -> response_node
      -> clarification/context_missing/capability_boundary -> response_node
      -> tool_plan -> validate_plan_node -> tool_executor_node
                   -> evidence_node -> answer_node -> critic_node -> response_node
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
DOTAMIND_LIVE_DATA_ENABLED=false
DOTAMIND_OPENDOTA_API_KEY=
DOTAMIND_STRATZ_TOKEN=
DOTAMIND_LLM_ENABLED=false
DOTAMIND_LLM_PROVIDER=deepseek
DOTAMIND_LLM_API_KEY=
DOTAMIND_LLM_BASE_URL=https://api.deepseek.com
DOTAMIND_LLM_MODEL=deepseek-chat
DOTAMIND_POLICY_PATH=
DOTAMIND_SESSION_STORE_BACKEND=memory
DOTAMIND_REDIS_URL=redis://localhost:6379/0
```

Policy is cached for the process lifetime. Restart the API after changing
`policy.yaml` or an override file.

See the repository [documentation index](../../docs/README.md) and
[configuration reference](../../docs/technical/configuration.md) for details.
