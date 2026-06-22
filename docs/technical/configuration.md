# Configuration Management

## Sources of Truth

```text
.env                          secrets and environment-specific values
apps/api/app/config/policy.yaml  business policy and tunable thresholds
apps/api/app/data/patches/       patch fact data
apps/api/app/resources/prompts/  prompt content
```

Do not put API keys, database credentials, or tokens in `policy.yaml`. Do not move patch facts or
prompt bodies into policy configuration.

## Policy Loading

`app/core/config.py` loads YAML with `yaml.safe_load()` and validates it through the immutable
Pydantic `AppPolicy` model. Unknown fields, missing fields, invalid ranges, inconsistent sample
sizes, and hero score weights that do not total 1.0 fail validation.

The default path is:

```text
apps/api/app/config/policy.yaml
```

Deployments may override it with:

```text
METAMIND_POLICY_PATH=C:/absolute/path/policy.yaml
```

Policy is cached for the process lifetime. Restart the API after editing the YAML file.

## Policy Sections

| Section | Responsibility |
|---|---|
| `opendota` | Request timeout and default transport cache |
| `team_report` | Time range, entity resolution, match sampling, concurrency, detail cache |
| `hero_report` | Result count, minimum sample, evidence thresholds, scoring, tiers |
| `patch_report` | Default patch, result count, neutral score, buff/nerf delta |
| `critic` | Evidence requirements and unsupported-signal rejection |
| `llm` | Orchestrator and hero-analyzer temperature/token limits |

## 中文说明

- 修改密钥、URL 或环境开关：编辑 `.env`。
- 修改战队采样、匹配阈值、英雄评分、版本评分、Critic 或 LLM 参数：编辑 `policy.yaml`。
- 更新版本事实：增加或修改 `app/data/patches/*.json`。
- 修改 Prompt 正文：编辑 `app/resources/prompts/*.md`。
- YAML 修改后需要重启 API；配置错误会在服务初始化时直接失败。
