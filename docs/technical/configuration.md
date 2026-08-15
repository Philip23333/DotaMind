# Configuration Management

## Sources of Truth

```text
.env                            environment, secrets, URLs, and feature flags
apps/api/app/config/policy.yaml business policy and tunable thresholds
apps/api/app/core/config.py     strict Pydantic settings and policy models
apps/api/app/data/catalog/      committed Valve hero/ability/item Catalog bundle
apps/api/app/data/patches/      patch fact data
apps/api/app/agentic/prompts/   Controller prompt renderers and versions
apps/api/app/resources/         debug UI resources
```

Do not put API keys, database credentials, tokens, or deployment URLs in
`policy.yaml`. Do not move patch facts or prompt bodies into business policy.

## Environment Settings

`Settings` in `app/core/config.py` uses `DOTAMIND_` as the sole environment
prefix. Previous prefixes are intentionally unsupported; update local and
deployed environment files before starting the API.

Important settings include:

| Setting | Responsibility |
|---|---|
| `DOTAMIND_ENVIRONMENT` | Environment label. |
| `DOTAMIND_API_V1_PREFIX` | API prefix, normally `/api/v1`. |
| `DOTAMIND_CORS_ORIGINS` | Allowed browser origins. |
| `DOTAMIND_DATABASE_URL` | PostgreSQL URL for durable Chat Sessions, Runs, and Turns. |
| `DOTAMIND_SESSION_STORE_BACKEND` / `DOTAMIND_REDIS_URL` | Session lease/cache backend and Redis connection. |
| `DOTAMIND_MAX_CONCURRENT_CHAT_RUNS` | Per-worker detached Chat Run concurrency. |
| `DOTAMIND_RUN_HEARTBEAT_SECONDS` / `DOTAMIND_RUN_STALE_SECONDS` / `DOTAMIND_RUN_SWEEPER_INTERVAL_SECONDS` | Chat Run liveness and stale-run recovery timing. |
| `DOTAMIND_LIVE_DATA_ENABLED` | Enables live provider calls. |
| `DOTAMIND_OPENDOTA_API_KEY` / `DOTAMIND_OPENDOTA_BASE_URL` | OpenDota access. |
| `DOTAMIND_PANDASCORE_TOKEN` / `DOTAMIND_PANDASCORE_BASE_URL` | PandaScore Dota 2 fixture access. The token is never logged or committed. |
| `DOTAMIND_STRATZ_TOKEN` / `DOTAMIND_STRATZ_GRAPHQL_URL` | STRATZ access. |
| `DOTAMIND_LLM_ENABLED` | Enables planner/answer LLM calls. |
| `DOTAMIND_LLM_PROVIDER` / `DOTAMIND_LLM_API_KEY` | LLM provider selection and secret. |
| `DOTAMIND_LLM_BASE_URL` / `DOTAMIND_LLM_MODEL` | OpenAI-compatible endpoint and model. |
| `DOTAMIND_POLICY_PATH` | Optional absolute policy YAML override. |

Use `.env.example` as the environment template. Never commit populated secrets.

## Policy Loading

`app/core/config.py` loads YAML with `yaml.safe_load()` and validates it through
the immutable `AppPolicy` model. Unknown fields, missing fields, invalid ranges,
inconsistent critic thresholds, and invalid sample-policy tiers fail validation.

The default path is:

```text
apps/api/app/config/policy.yaml
```

Deployments may override it with:

```text
DOTAMIND_POLICY_PATH=C:/absolute/path/policy.yaml
```

Policy is cached for the process lifetime. Restart the API after editing the
YAML or changing the override path.

The `pandascore` policy controls the fixture transport timeout, short-lived
cache TTL, and maximum upstream page size. A missing
`DOTAMIND_PANDASCORE_TOKEN` only affects PandaScore tool execution; it does not
prevent unrelated tools or the application from starting.

The `cross_source_match_resolution` policy controls deterministic PandaScore
Game to OpenDota/Valve matching. `start_time_tolerance_seconds` defaults to
1800 and `duration_tolerance_seconds` defaults to 5. These are hard filters,
not weights or closest-match scoring.

## Local Game Data

The Valve Catalog and patch records are committed runtime snapshots, not local
cache files. Regenerate them from Valve's public Dota 2 Datafeed with:

```powershell
cd apps/api
uv run python scripts/sync_game_data.py --patch latest
```

The command atomically writes `app/data/catalog/manifest.json`, bilingual hero,
ability and item JSON files, developer-only `sync_audit.json`, and the selected
`app/data/patches/<version>.json`. Official English and Simplified Chinese names
come from Valve; community hero aliases are reviewed separately in
`scripts/hero_aliases_zh.yaml`. Patch polarity is classified conservatively and
left `neutral` when the direction is unclear. Review generated diffs before
committing them; request-time code never downloads or generates these files.

## Policy Sections

| Section | Responsibility |
|---|---|
| `version` | Policy schema version; currently `1`. |
| `opendota` | Request timeout and default transport cache TTL. |
| `stratz` | Default and maximum completed-week fan-out. |
| `cross_source_match_resolution` | Hard start-time and duration tolerances for inferred Valve match mappings. |
| `team_report` | Time range, team resolution, match-detail sampling, concurrency, and cache. |
| `hero_report` | Result limits, sample gates, evidence thresholds, and normalization ranges. |
| `patch_report` | Default patch, result count, neutral score, and change delta. |
| `critic` | Evidence, mock, confidence, freshness, and team sample-quality gates. |
| `llm.orchestrator` | Planner temperature, token limit, and retry model defaults. |
| `planning.sample_policy` | Per-tool relaxed/default/strict sample thresholds and target argument names. |
| `conversation` | Recent dialogue cache, older-history lookup, compact audit, and legacy SessionStore capacity limits. |

### STRATZ Window Policy

`stratz.weeks_back_default` is applied when a weekly STRATZ tool receives a
null window. `stratz.weeks_back_max` bounds provider fan-out because N weeks
usually means N STRATZ calls per tool. Player tools use their own `take`, `days`,
and `match_take` parameters instead of this weekly policy.

### Planner Sample Policy

`planning.sample_policy.tools` is the single source of truth for planner-side
sample thresholds. Each entry declares:

- `arg`: the registered tool input field to populate.
- `relaxed`: small-sample tier for explicitly permissive queries.
- `default`: value backfilled when the planner omits or nulls the argument.
- `strict`: large-sample tier for robust/high-confidence requests.

The configured tool and argument must exist in the registry. Tiers must satisfy
`relaxed <= default <= strict`, and tests keep policy defaults aligned with tool
input-model defaults.

### Conversation Policy

`conversation` controls the Redis recent-message window and bounded audit memory. Fields:

- `recent_dialogue_max_chars`: character budget for the Redis recent dialogue window.
- `history_lookup_max_turns`: maximum older turns returned by one internal lookup.
- `history_lookup_max_chars`: character budget for retrieved older messages.
- `history_lookup_max_per_run`: maximum history lookups in one Run.
- `max_turns_per_session`: compact Turns retained by the legacy SessionStore list;
  it does not cap PostgreSQL Chat transcript retention.
- `max_sessions`: legacy InMemorySessionStore inactive-session LRU capacity target.
- `answer_summary_max_chars`: per-turn answer summary cap.
- `turn_query_max_chars`: per-turn stored query cap.

All fields have defaults, so a `policy.yaml` without a `conversation` section
still loads. PostgreSQL is the complete conversation source; Redis only caches
recent messages and coordinates the stateful Run. A request without `session_id`
remains stateless.
History is supplied as real user/assistant messages. It is neither an
automatically valid fact cache nor automatically stale; the Controller decides
whether a stable, same-version answer can be reused and when a tool must refresh
it. No discourse graph or entity-specific memory is configured. The internal
History Lookup budget must leave one Controller call for the final decision:
`planning.runtime.max_controller_calls >= conversation.history_lookup_max_per_run + 1`.
The Controller also receives request-local game, request time, Catalog patch, and
snapshot generation time; these freshness signals are not stored in Session or
Redis history.
Legacy InMemorySessionStore transactions preserve active/waiting entries while
converging to `max_sessions`; this does not define PostgreSQL Chat retention.

## Removed Configuration Sources

The old `opendota.json`, `signals.yaml`, and `critic_rules.yaml` sources have
been removed. Do not recreate parallel policy files unless the configuration
boundary is deliberately redesigned.

## 中文说明

- 修改密钥、URL 或环境开关：编辑 `.env`。
- 修改 OpenDota/STRATZ 边界、采样阈值、报告规则、Critic、LLM 或 Planner
  Sample Policy：编辑 `apps/api/app/config/policy.yaml`。
- 更新版本事实：增加或修改 `apps/api/app/data/patches/*.json`。
- 更新英雄、技能、物品或中文名：运行离线同步脚本，并审查 Catalog 五个文件、
  patch 文件与 `apps/api/scripts/hero_aliases_zh.yaml` 的差异。
- 修改 Controller Prompt：编辑 `apps/api/app/agentic/prompts/`；修改调试页面资源：
  编辑 `apps/api/app/resources/`。
- YAML 修改后需要重启 API；配置错误会在服务初始化时直接失败。
