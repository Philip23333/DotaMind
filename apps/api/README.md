# DotaMind API

FastAPI backend for the DotaMind V3 agentic workflow.

The old fixed report/query pipeline has been removed. The current API surface is:

- `GET /health`
- `POST /api/v1/plan`
- `POST /api/v1/plan/stream` (stateless debug only)
- `/api/v1/chat/sessions` session CRUD
- `/api/v1/chat/.../runs` create/query/active/events/cancel
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
answer, review, errors and trace. Conversation recall, history-grounded answers,
clarification, missing context and capability boundaries skip the business
tool/evidence/critic path.

## Multi-chat Runs

`/api/v1/plan` and `/api/v1/plan/stream` are stateless debug endpoints. Formal multi-turn
chat uses PostgreSQL-backed sessions plus the detached Chat Run lifecycle:

```bash
BROWSER_ID=$(python -c "import uuid; print(uuid.uuid4())")
SESSION_ID=$(curl -s -X POST http://localhost:8001/api/v1/chat/sessions \
  -H "X-DotaMind-Browser-Id: $BROWSER_ID" | python -c "import json,sys; print(json.load(sys.stdin)['session_id'])")
REQUEST_ID=$(python -c "import uuid; print(uuid.uuid4())")
curl -s -X POST "http://localhost:8001/api/v1/chat/sessions/$SESSION_ID/runs" \
  -H "X-DotaMind-Browser-Id: $BROWSER_ID" \
  -H "Content-Type: application/json" \
  -d "{\"request_id\":\"$REQUEST_ID\",\"query\":\"enemy picked Lina, what should I pick?\",\"game\":\"dota2\"}"
curl -N "http://localhost:8001/api/v1/chat/runs/<RUN_ID>/events?after=0" \
  -H "X-DotaMind-Browser-Id: $BROWSER_ID"
```

The Run Repository owns status, fencing, idempotency and atomic Turn completion in PostgreSQL.
Redis carries replayable allowlisted events and cancel notifications; it is not the final Turn
authority. Closing the event stream only closes observation. Refreshing the browser reads the
active Run from the session and replays events from sequence zero. Worker shutdown/stale
recovery marks active Runs `interrupted`; it does not resume a model checkpoint.

Current conditional LangGraph path:

```text
controller_node
  -> decision_validate_node
      -> direct_answer -> conversation_answer_node -> attempt_finalize_node
      -> clarification/context_missing/capability_boundary -> attempt_finalize_node
      -> tool_plan -> validate_plan_node -> tool_executor_node
                   -> conversation.history_lookup -> controller_node
                   -> evidence_node -> answer_node -> critic_node
  -> attempt_finalize_node -> recovery_node -> run_finalize_node -> response_node
```

## Output Contracts

- `natural_language_answer`
- `patch_impact_report`
- `role_meta_report`
- `team_recent_report`

The contract registry in `app/agentic/planning/contracts.py` is authoritative.

## Registered Tools

Committed Valve Catalog:

- `resolve_hero`
- `dota.hero_attributes`
- `dota.hero_abilities`
- `dota.hero_talent_tree`
- `resolve_item`
- `dota.item_info`

英雄与物品图片由 `scripts/sync_game_data.py --images-only` 从 Valve 官方
CDN 下载到 `app/data/catalog/images/`，API 通过
`/api/v1/assets/dota/heroes/{id}.png` 和
`/api/v1/assets/dota/items/{id}.png` 提供本地静态访问。Catalog 英雄/物品查询
结果携带对应的 `image_path`；请求运行时不访问外部图片 CDN。

`opendota.match_details` 的选手、背包/装备、中立物品和 BP 记录也会保留确定性的
`hero_image_path` / `item_image_path`；Catalog 未命中或 ID 缺失时字段为 `null`，不会
猜测图片路径。它们复用上述静态资源路由，并随 `tool_results` 与对应 evidence 透传。

STRATZ:

- `stratz.pair_lane_outcome`
- `stratz.hero_matchup_ranking`
- `stratz.hero_synergy_ranking`
- `stratz.lane_meta_global`
- `stratz.hero_position_stats`
- `stratz.hero_daily_trends`
- `stratz.filter_ranked_heroes_by_position`
- `stratz.player_profile`
- `stratz.player_recent_matches`
- `stratz.player_hero_performance`

OpenDota:

- `opendota.resolve_team`
- `opendota.team_recent_matches`
- `opendota.team_players`
- `opendota.team_heroes`
- `opendota.hero_stats_by_role`
- `opendota.match_details`

PandaScore Dota 2 Fixture:

- `pandascore.resolve_competition`
- `pandascore.list_matches`
- `pandascore.resolve_match_games`

Cross-source match resolution:

- `dota.resolve_valve_matches`

`pandascore.resolve_match_games` returns all provider-exposed games when no game
number is supplied. `dota.resolve_valve_matches` consumes the competition and
game-context lists, then matches each game to a unique OpenDota league match
using team IDs, hard time/duration tolerances, series game position, and winner
consistency. Its Valve IDs are auditable inferences, not native PandaScore
fields. Ambiguous or missing signals remain explicit statuses.

PandaScore Fixture IDs and Valve match IDs are distinct. The free Fixture
response currently does not expose the Valve ID. `opendota.match_details`
accepts Valve Match IDs only, normally from the separately declared cross-source
inference; it must not receive PandaScore Series, Match, or Game IDs. No guessing
or paid endpoint is used.

Local patch records:

- `patch.get_records`
- `patch.hero_changes`
- `patch.item_changes`

Request-local conversation context:

- `conversation.history_lookup`

The `ToolRegistry` definitions are authoritative for arguments, output paths,
reference contracts, and evidence kinds.

## Configuration

Secrets, environment-specific URLs, and feature flags are loaded from `.env`.
Business policy is loaded from `app/config/policy.yaml` and validated by
Pydantic at startup.

```text
DOTAMIND_LIVE_DATA_ENABLED=false
DOTAMIND_OPENDOTA_API_KEY=
DOTAMIND_PANDASCORE_TOKEN=
DOTAMIND_PANDASCORE_BASE_URL=https://api.pandascore.co
DOTAMIND_STRATZ_TOKEN=
DOTAMIND_LLM_ENABLED=false
DOTAMIND_LLM_PROVIDER=deepseek
DOTAMIND_LLM_API_KEY=
DOTAMIND_LLM_BASE_URL=https://api.deepseek.com
DOTAMIND_LLM_MODEL=deepseek-chat
DOTAMIND_TEST_OBSERVER_ENABLED=false
DOTAMIND_POLICY_PATH=
DOTAMIND_SESSION_STORE_BACKEND=memory
DOTAMIND_REDIS_URL=redis://localhost:6379/0
```

Policy is cached for the process lifetime. Restart the API after changing
`policy.yaml` or an override file.

`DOTAMIND_TEST_OBSERVER_ENABLED=true` adds full Controller/Answer prompts, model
outputs, and resolved tool inputs/outputs to the short-lived Run event stream.
It is disabled by default and must only be enabled in a local test environment;
the observation payload is not written to the PostgreSQL transcript.

### 赛事届次与运行时失败状态

PandaScore 赛事 resolver 接受可选届次年份；缺省年份时由实时 Fixture 的进行中、
历史和即将开始时间确定最近一届，显式年份不会被替换。解析结果带有选择模式和
候选审计元数据。公共 runtime 的每个工具调用还会报告 `handler_entered`、
`dispatch_stage` 与安全失败码，帮助 `/debug/plan` 和 Chat UI 区分引用未执行与
handler 执行失败；原始异常和内部引用不对外公开。

See the repository [documentation index](../../docs/README.md) and
[configuration reference](../../docs/technical/configuration.md) for details.
