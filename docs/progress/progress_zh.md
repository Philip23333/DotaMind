# MetaMind 当前进度

> 最后更新：2026-06-17
> 当前事实：后端已激进重构为 canonical v2.1 pipeline。旧 `agents/`、`services/`、`tools/` 源码已删除。

## 当前架构

```text
api/v1/routes.py
  -> api/v1/mappers.py
  -> application/query_service.py 或 application/report_service.py
  -> pipeline/orchestrator.py
  -> pipeline/retriever.py
  -> pipeline/analyzer.py
  -> pipeline/critic.py
  -> pipeline/formatter.py
  -> api/v1/mappers.py
```

## 目录职责

```text
app/api/v1/        FastAPI schema、routes、HTTP/domain mapper
app/application/   QueryService、ReportService、service catalog
app/domain/        evidence、task、report dataclass
app/pipeline/      Orchestrator、Retriever、Analyzer、Critic、Formatter
app/integrations/  OpenDota、patch notes、STRATZ client
app/data/          fixtures 与 patch JSON
app/llm/           LLM provider 与 prompt loader
app/core/          settings
```

## 当前入口

```text
GET  /health
GET  /api/v1/services
POST /api/v1/query
POST /api/v1/meta-report
POST /api/v1/patch-impact
POST /api/v1/team-report
POST /api/v1/verify-claim
```

`/api/v1/query/experimental` 已删除。前端 `AskConsole` 现在调用 `/api/v1/query`。

## 数据策略

默认不开启外部 live data，避免测试和本地开发被 OpenDota 网络拖慢。

```text
METAMIND_LIVE_DATA_ENABLED=false  # 默认
METAMIND_LIVE_DATA_ENABLED=true   # 显式启用 OpenDota live retrieval
```

Patch impact 仍读取本地 `apps/api/app/data/patches/7_41d.json`。

## LLM 状态

当前 LLM 仍是可选能力：`AnalyzerAgent` 在 `METAMIND_LLM_ENABLED=true` 且 provider 可用时，为 meta hero 生成 `reasons` 和 `practice_advice`。Orchestrator 与 Critic 目前仍是规则实现，但边界已放在 `pipeline/`，后续可以替换为 LLM function calling / LLM critic。

## 验证状态

已通过：

```bash
cd apps/api && python -m pytest
cd apps/api && python -m ruff check app tests
npm run typecheck --workspace apps/web
```

最近结果：后端 `16 passed, 3 skipped`，后端 lint 通过，前端 TypeScript typecheck 通过。
