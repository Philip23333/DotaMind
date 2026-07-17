# Configuration Management

## Sources of Truth

```text
.env                            environment, secrets, URLs, and feature flags
apps/api/app/config/policy.yaml business policy and tunable thresholds
apps/api/app/core/config.py     strict Pydantic settings and policy models
apps/api/app/data/heroes/       committed hero ID/name/alias snapshot
apps/api/app/data/patches/      patch fact data
apps/api/app/resources/         prompt and debug UI resources
```

Do not put API keys, database credentials, tokens, or deployment URLs in
`policy.yaml`. Do not move patch facts or prompt bodies into business policy.

## Environment Settings

`Settings` in `app/core/config.py` uses the `METAMIND_` prefix. The prefix is a
known naming-migration debt; it remains the current runtime contract.

Important settings include:

| Setting | Responsibility |
|---|---|
| `METAMIND_ENVIRONMENT` | Environment label. |
| `METAMIND_API_V1_PREFIX` | API prefix, normally `/api/v1`. |
| `METAMIND_CORS_ORIGINS` | Allowed browser origins. |
| `METAMIND_LIVE_DATA_ENABLED` | Enables live provider calls. |
| `METAMIND_OPENDOTA_API_KEY` / `METAMIND_OPENDOTA_BASE_URL` | OpenDota access. |
| `METAMIND_STRATZ_TOKEN` / `METAMIND_STRATZ_GRAPHQL_URL` | STRATZ access. |
| `METAMIND_LLM_ENABLED` | Enables planner/answer LLM calls. |
| `METAMIND_LLM_PROVIDER` / `METAMIND_LLM_API_KEY` | LLM provider selection and secret. |
| `METAMIND_LLM_BASE_URL` / `METAMIND_LLM_MODEL` | OpenAI-compatible endpoint and model. |
| `METAMIND_POLICY_PATH` | Optional absolute policy YAML override. |

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
METAMIND_POLICY_PATH=C:/absolute/path/policy.yaml
```

Policy is cached for the process lifetime. Restart the API after editing the
YAML or changing the override path.

## Local Game Data

Hero constants and patch records are committed runtime snapshots, not local
cache files. Regenerate both from Valve's public Dota 2 datafeed with:

```powershell
cd apps/api
uv run python scripts/sync_game_data.py --patch latest
```

The command writes `app/data/heroes/dota2_heroes.yaml` and the selected
`app/data/patches/<version>.json`. Official English and Simplified Chinese hero
names come from Valve; community aliases are reviewed separately in
`scripts/hero_aliases_zh.yaml`. Patch polarity is classified conservatively and
left `neutral` when the direction is unclear. Review generated diffs before
committing them; the API never downloads or generates these files at request
time.

## Policy Sections

| Section | Responsibility |
|---|---|
| `version` | Policy schema version; currently `1`. |
| `opendota` | Request timeout and default transport cache TTL. |
| `stratz` | Default and maximum completed-week fan-out. |
| `team_report` | Time range, team resolution, match-detail sampling, concurrency, and cache. |
| `hero_report` | Result limits, sample gates, evidence thresholds, and normalization ranges. |
| `patch_report` | Default patch, result count, neutral score, and change delta. |
| `critic` | Evidence, mock, confidence, freshness, and team sample-quality gates. |
| `llm.orchestrator` | Planner temperature, token limit, and retry model defaults. |
| `planning.sample_policy` | Per-tool relaxed/default/strict sample thresholds and target argument names. |

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

## Removed Configuration Sources

The old `opendota.json`, `signals.yaml`, and `critic_rules.yaml` sources have
been removed. Do not recreate parallel policy files unless the configuration
boundary is deliberately redesigned.

## 中文说明

- 修改密钥、URL 或环境开关：编辑 `.env`。
- 修改 OpenDota/STRATZ 边界、采样阈值、报告规则、Critic、LLM 或 Planner
  Sample Policy：编辑 `apps/api/app/config/policy.yaml`。
- 更新版本事实：增加或修改 `apps/api/app/data/patches/*.json`。
- 更新英雄 ID、名称、中文名或俗称：运行离线同步脚本，并审查
  `apps/api/scripts/hero_aliases_zh.yaml` 与生成文件的差异。
- 修改 Prompt 或调试页面资源：编辑 `apps/api/app/resources/` 下的对应文件。
- YAML 修改后需要重启 API；配置错误会在服务初始化时直接失败。
