# MetaMind 施工进度文档

> 最后更新：2026-06-16  
> 面向对象：人类开发者 + 后续接手本项目的 Agent  
> 当前重点：v2.1 实验链路已可跑通，LLM 仅接在 Analyzer 的 meta_report 英雄洞察阶段。

## 项目概览

MetaMind 是一个可组合的 Dota2 电竞情报 Agent，将版本更新、比赛数据和职业战队表现转化为可验证、可调用、未来可付费的 Meta 分析报告。

当前设计目标仍是 `v2.1`：3 Agent + 2 Tool + Critic 闭环。

设计文档：`docs/design/MetaMind_MVP_v2.1.md`

## 给接手 Agent 的当前事实

请优先相信本节，而不是 README 或旧 milestone 文档中的零散描述。

1. 后端已有两套链路并存。
2. 旧稳定服务仍存在：`MetaReportService`、`PatchImpactService`、`TeamReportService`、`ClaimVerificationService`。
3. 新 v2.1 实验入口是：`POST /api/v1/query/experimental`。
4. v2.1 实验入口目前不是完整 LLM Agent 系统。
5. 当前真正调用 LLM 的模块只有：`AnalyzerAgent` 的 `meta_report` 英雄洞察生成。
6. `OrchestratorAgent` 目前是关键词规则路由，不是 LLM function calling。
7. `CriticAgent` 目前只有规则审核，不是 LLM critic。
8. `RetrieverTool` 和 `FormatterTool` 是 deterministic tools，不调用 LLM。
9. `/api/v1/query/experimental` 对四类 service 都能返回 200。
10. `meta_report` 走 v2.1 实验链路；`patch_impact`、`team_report`、`claim_verification` 目前 fallback 到旧稳定服务。
11. 自然语言 query 里的 role 尚未解析。`Strongest midlane heroes` 仍会被硬编码成 `offlane`。
12. 前端 `AskConsole` 已接入 v2.1 实验查询，但为了避开 Next 代理问题，浏览器直接请求 `http://127.0.0.1:8000/api/v1/query/experimental`。

## 当前状态总览

| 模块 | 当前状态 | 真实说明 |
|------|----------|----------|
| Meta Report 旧服务 | ✅ 可用 | OpenDota `/heroStats` + 本地 patch JSON，纯规则/公式，无 LLM |
| Meta Report v2.1 实验链路 | ✅ 可用 | Retriever + Analyzer + Critic + Formatter；Analyzer 会为 top 10 英雄逐个调用 LLM 生成 `reasons` 和 `practice_advice` |
| Patch Impact | ✅ 可用 | 旧稳定服务，读取 `7_41d.json` 的 189 条改动；experimental endpoint 中 fallback 到该服务 |
| Team Report | ✅ 可用 | 旧稳定服务，OpenDota 可用时接真实数据，失败时 fallback 到 mock；experimental endpoint 中 fallback 到该服务 |
| Claim Verification | ⚠️ Mock/规则 | 旧稳定服务，硬编码规则；experimental endpoint 中 fallback 到该服务并经过规则 Critic |
| Orchestrator | ⚠️ 规则路由 | 关键词判断 service 类型；未解析 role；未接 LLM function calling |
| Analyzer | ✅ 部分 LLM | 仅 meta_report 英雄洞察阶段调用 LLM；评分/evidence 仍是规则 |
| Critic | ⚠️ 规则审核 | Layer 1 规则：无证据或 unsupported signal 会 reject；Layer 2 LLM 未实现 |
| RetrieverTool | ✅ meta 可用 | `retrieve_meta()` 接 OpenDota + patch JSON；其他 retrieve 方法存在但主 experimental fallback 未使用 |
| FormatterTool | ✅ meta 可用 | 当前主要格式化 `MetaReportResponse` |
| 前端 Dashboard | ✅ 可运行 | `AskConsole` 可调用 experimental endpoint；其他 SSR 面板仍调用旧 API，有 mock fallback |
| CAP 付费集成 | ❌ 未实现 | 只有 service catalog 静态价格形态 |

## 当前主要入口

### 后端启动

```bash
npm run dev:api
```

实际命令：

```bash
cd apps/api && python -m uvicorn app.main:app --reload --port 8000
```

### 前端启动

```bash
npm run dev:web
```

前端地址：

```text
http://localhost:3012
```

### v2.1 实验接口

```bash
curl -X POST http://127.0.0.1:8000/api/v1/query/experimental \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"Strongest offlane heroes\",\"game\":\"dota2\"}"
```

### 稳定旧接口

```text
POST /api/v1/meta-report
POST /api/v1/patch-impact
POST /api/v1/team-report
POST /api/v1/verify-claim
GET  /api/v1/services
```

## 当前 v2.1 experimental 数据流

### meta_report 查询

```text
POST /api/v1/query/experimental
  -> ExperimentalService.handle_query()
  -> OrchestratorAgent.plan()
       当前只判断 service 类型，meta role 写死为 offlane
  -> RetrieverTool.retrieve_meta(role="offlane", patch="latest")
       OpenDota hero stats + 本地 patch JSON
  -> AnalyzerAgent.analyze_meta_report()
       规则公式计算 meta_score/confidence/evidence
       若 llm_enabled=True，为每个 hero 调用 LLM 生成 reasons/practice_advice
  -> CriticAgent.review_evidence()
       Layer 1 规则审核
  -> FormatterTool.format_meta_report()
  -> NaturalLanguageQueryResponse
```

### patch/team/claim 查询

```text
POST /api/v1/query/experimental
  -> ExperimentalService.handle_query()
  -> OrchestratorAgent.plan()
  -> fallback 到旧稳定 service
       patch_impact        -> PatchImpactService
       team_report         -> TeamReportService
       claim_verification  -> ClaimVerificationService + CriticAgent.review_evidence()
  -> NaturalLanguageQueryResponse
```

## LLM 当前实现范围

### 已实现

LLM provider：

```text
apps/api/app/llm/provider.py
```

Analyzer 调用：

```text
apps/api/app/agents/analyzer.py
```

调用链：

```text
ExperimentalService._handle_meta_report()
  -> AnalyzerAgent.analyze_meta_report()
  -> AnalyzerAgent._generate_hero_insights()
  -> self.llm.complete_json(...)
  -> OpenAICompatibleProvider.complete_json()
  -> DeepSeek/OpenAI-compatible API
```

LLM 生成字段：

```text
HeroRecommendation.reasons
HeroRecommendation.practice_advice
```

### 未实现

```text
Orchestrator LLM function calling
Analyzer 对 patch/team/claim 的统一 LLM task_type 分析
Critic Layer 2 LLM 审核
LLM retry / budget / cache / batching
```

## LLM 日志

已在关键流程点打 `INFO/WARNING/ERROR` 日志，方便调用时观察控制台。

日志覆盖：

```text
Experimental query start/complete
Orchestrator planned service
Retriever start/complete
Analyzer start/complete
每个 hero 的 score/evidence
每个 hero 的 LLM insight request start/success/failure
LLM provider complete_json start/success/failure
Critic review result
Formatter complete
fallback service start/complete
```

日志不会打印：

```text
API key
完整 prompt
完整 LLM response
完整用户 query
```

注意：`httpx` 也会打印请求状态，例如：

```text
INFO:httpx:HTTP Request: POST https://api.deepseek.com/chat/completions "HTTP/1.1 200 OK"
```

## 前端当前实现

关键文件：

```text
apps/web/src/components/AskConsole.tsx
apps/web/src/lib/api.ts
apps/web/src/types/report.ts
```

`AskConsole` 行为：

```text
用户输入 query
  -> runExperimentalQuery(query)
  -> fetch http://127.0.0.1:8000/api/v1/query/experimental
  -> 页面内展示 routed_service、trace、top 3 hero sample 或 summary
```

为什么使用 `127.0.0.1`：

1. 之前尝试过 Next route handler 和 rewrites 代理。
2. 浏览器路径里出现过 `Remote Address: [::1]:3012` 且 Next 返回 500。
3. 后端没有日志，说明请求停在 Next dev server。
4. 最终改成浏览器直连 FastAPI IPv4 地址，避开 Next 代理问题。

当前 CORS 允许：

```text
http://localhost:3000
http://localhost:3012
http://localhost:3013
```

## 已完成工作

### 数据源与旧稳定服务

1. OpenDota REST API 已接入。
2. 本地 patch JSON 已结构化：`apps/api/app/data/patches/7_41d.json`。
3. Hero role mapping 已有 override 表。
4. 旧 `meta_report`、`patch_impact`、`team_report`、`claim_verification` 服务可用。
5. 前端 Dashboard 可运行并带 mock fallback。

### v2.1 骨架和实验链路

1. 新增 `agents/orchestrator.py`、`agents/analyzer.py`、`agents/critic.py`。
2. 新增 `tools/retriever.py`、`tools/formatter.py`。
3. 新增 `config/signals.yaml`、`config/critic_rules.yaml`。
4. 新增 `services/experimental_service.py`。
5. 新增 `/api/v1/query/experimental`。
6. experimental endpoint 对四类 service 都能返回结果。
7. `patch/team/claim` 未完成 v2.1 原生链路时 fallback 到旧稳定服务，避免 500。

### LLM 增强

1. 新增 LLM provider 抽象，当前支持 DeepSeek/OpenAI-compatible API。
2. `AnalyzerAgent` 可调用 LLM 生成英雄推荐理由和练习建议。
3. LLM 失败时不会阻断基础报告，会返回空 `reasons/practice_advice`。
4. 已加关键流程日志。

## 当前测试状态

最近验证：

```bash
cd apps/api
python -m pytest
```

结果：

```text
17 passed
```

前端类型检查：

```bash
npm run typecheck
```

结果：

```text
tsc --noEmit passed
```

触及文件 Ruff：

```bash
cd apps/api
python -m ruff check app\main.py app\llm\provider.py app\agents\analyzer.py app\services\experimental_service.py app\tools\formatter.py
```

结果：

```text
All checks passed
```

注意：全量 `python -m ruff check .` 可能仍会命中旧文件中的既有 lint 问题，接手 Agent 不要误以为全是本轮改动导致。

## 已知限制和坑

1. Orchestrator 不解析 role。

   `Strongest midlane heroes`、`carry recommendations`、`support heroes` 目前仍可能进入 `MetaReportRequest(role="offlane")`。

   位置：`apps/api/app/agents/orchestrator.py`

2. LLM 调用是逐英雄串行。

   top 10 英雄会产生 10 次 LLM 请求，当前单次 experimental meta 查询约 20-30 秒。

3. LLM API key 当前通过 settings 读取，但仓库中曾出现硬编码默认值。

   接手 Agent 应优先改为只从 `.env` 读取，避免把真实 key 写进代码或日志。

4. Critic 不是 LLM critic。

   当前只检查 evidence 是否为空、是否存在 unsupported signal。

5. Claim Verification 仍是规则/mock。

   未真正聚合 patch JSON + OpenDota 证据。

6. Patch impact score 仍是简单 buff/nerf 计数。

   不区分改动强度。

7. Team report 的 hero pool depth 使用历史数据，不是近期窗口。

8. 前端 SSR 面板仍依赖后端运行，否则 fallback 到 mock。

9. `README.md` 和部分 milestone 文档可能过时。

   当前交接请以本文件和代码为准。

## 建议下一步

### 高优先级

1. 给 `OrchestratorAgent` 增加 role 解析。

   支持：`midlane/mid/position 2`、`carry/pos 1`、`offlane/pos 3`、`support/pos 4/pos 5`。

2. 移除代码中的 LLM API key 默认值。

   只允许从 `.env` 或安全 secret 注入。

3. 降低 LLM 延迟。

   可选方案：只给 top 3 调 LLM、并发调用、缓存、或增加 `llm_enabled` 前端/请求开关。

4. 为 experimental endpoint 增加 role 相关测试。

5. 更新 API 文档，明确 `/api/v1/query/experimental` 的 fallback 行为。

### 中优先级

1. 实现 Critic Layer 2 LLM 审核。
2. 实现 Claim Verification 真实证据聚合。
3. 将 patch/team/claim 从 fallback 迁移到 v2.1 原生链路。
4. 给 Orchestrator 增加 LLM function calling 或更强的 deterministic parser。
5. 增加 LLM budget、timeout、retry、cache。

### 低优先级

1. CAP 集成。
2. 数据库持久化报告历史。
3. STRATZ GraphQL 精细化 draft 数据。
4. Demo 视频。

## 当前目录结构重点

```text
apps/api/app/
├── agents/
│   ├── orchestrator.py       # v2.1 规则 Orchestrator，当前不解析 role
│   ├── analyzer.py           # v2.1 Analyzer，meta_report 中调用 LLM
│   ├── critic.py             # v2.1 规则 Critic
│   ├── data_agent.py         # 旧稳定链路仍使用
│   ├── patch_agent.py        # 旧稳定链路仍使用
│   ├── reasoning_agent.py    # 旧稳定链路仍使用
│   ├── verification_agent.py # 旧稳定链路仍使用
│   └── report_agent.py       # 旧稳定链路仍使用
├── llm/
│   └── provider.py           # DeepSeek/OpenAI-compatible provider
├── tools/
│   ├── retriever.py          # v2.1 deterministic retriever
│   └── formatter.py          # v2.1 deterministic formatter
├── services/
│   ├── experimental_service.py       # v2.1 experimental orchestration service
│   ├── meta_report_service.py        # 旧稳定 meta report
│   ├── patch_impact_service.py       # 旧稳定 patch impact
│   ├── team_report_service.py        # 旧稳定 team report
│   └── claim_verification_service.py # 旧稳定 claim verification
└── api/v1/routes.py          # HTTP routes，包括 /query/experimental
```

```text
apps/web/src/
├── components/AskConsole.tsx # v2.1 experimental UI 入口
├── lib/api.ts                # runExperimentalQuery 直连 127.0.0.1:8000
└── types/report.ts           # NaturalLanguageQueryResponse 等类型
```

## 文档目录

```text
docs/
├── design/
│   ├── MetaMind_MVP_v1.md
│   ├── MetaMind_MVP_v2.md
│   └── MetaMind_MVP_v2.1.md
├── technical/
│   ├── api.md
│   ├── architecture.md
│   └── cap-integration.md
└── progress/
    ├── progress_zh.md
    └── progress_en.md
```
