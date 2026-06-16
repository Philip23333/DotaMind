# MetaMind 施工进度文档

> 最后更新：2026-06-16（v2.1 架构迁移中 - Milestone 1 完成 ✅）

## 项目概览

MetaMind 是一个可组合的电竞情报 Agent，将 Dota2 版本更新、比赛数据和职业战队表现转化为可验证、可付费调用的 Meta 分析报告。

**当前架构版本：v2.1**（3 Agent + 2 Tool + 对抗式 Critic 闭环）。详见 `docs/design/MetaMind_MVP_v2.1.md`。

---

## 当前状态总览

| 模块 | 状态 | 数据来源 |
|------|------|----------|
| Meta Report（英雄推荐） | ✅ 真实数据 | OpenDota /heroStats + patch JSON |
| Patch Impact（版本影响） | ✅ 真实数据 | 本地 patch JSON（189 条改动） |
| Team Report（战队分析） | ✅ 真实数据 | OpenDota /teams + /matches + /heroes |
| Claim Verification（断言校验） | ⚠️ Mock | 规则硬编码 |
| Service Catalog（服务目录） | ✅ 静态配置 | 不需要外部数据 |
| CAP 付费集成 | ❌ 未实现 | — |
| 前端 Dashboard | ✅ 可运行 | 依赖后端启动 |

---

## 已完成工作

### 第一阶段：数据源接入

1. **OpenDota REST API 接入**
   - `/heroStats`：英雄胜率、登场率、Ban 率、职业比赛数据
   - `/teams`：战队搜索（支持名称和 tag 模糊匹配）
   - `/teams/{id}/matches`：最近 N 场比赛记录
   - `/teams/{id}/heroes`：战队英雄池统计
   - 内存缓存 TTL 1h，避免重复请求

2. **Patch Notes 结构化**
   - 手工录入 7.41d 版本完整 patch notes → `data/patches/7_41d.json`
   - 189 条改动（116 buffs / 71 nerfs / 2 neutral）
   - 覆盖英雄、物品、中立物品、附魔四类

3. **英雄 Role 映射**
   - OpenDota role tags → 标准位置（carry/mid/offlane/support）
   - 40+ 英雄 override 表修正分类偏差（如 Mars/Tidehunter 归入 offlane）

### 第二阶段：服务逻辑实现

4. **Meta Report Service**（async）
   - OpenDota 高分段胜率（Ancient+）作为核心排序依据
   - Patch JSON 注入 `patch_impact_score`（buff +0.15, nerf -0.15）
   - 加权公式计算 meta_score（胜率 30% + 登场率 25% + 职业存在感 20% + 版本影响 15% + 趋势 10%）
   - 返回 top 10 英雄，OpenDota 失败时降级到 mock

5. **Patch Impact Service**
   - 从 JSON 统计 winners（buff 最多的英雄）和 losers（nerf 最多的英雄）
   - 自动生成 summary、item impacts、lineup trends
   - Confidence 根据数据完整度动态计算（0.6~0.9）

6. **Team Report Service**（async）
   - 支持任意战队查询（名称/tag 模糊匹配）
   - 最近 30 场胜负记录
   - 签名英雄 top 5（按历史 games_played 排序）
   - Hero pool depth（≥30 场的英雄数）
   - Draft flexibility、Patch adaptation score
   - 胜/负场均时长分析
   - 失败时降级到 mock

### 第三阶段：工程基础

7. **测试**
   - 4 个服务测试全部通过（pytest + pytest-asyncio）
   - meta_report / patch_impact / team_report / claim_verification

8. **环境配置**
   - `.env` 文件配置 CORS（支持 3000/3012/3013 端口）
   - docker-compose 预留 Postgres + Redis（未接入代码）
   - pydantic-settings 管理配置

---

## v2.1 架构迁移进度

### ✅ Milestone 1：数据流通（已完成）

**目标**：打通 Orchestrator → Retriever → Analyzer → Critic 的完整数据流，暂不用 LLM。

| 子任务 | 状态 | 说明 |
|------|------|------|
| 骨架文件创建 | ✅ 完成 | orchestrator/analyzer/critic/retriever/formatter 已创建 |
| 配置文件 | ✅ 完成 | signals.yaml / critic_rules.yaml 已建立 |
| Retriever 连接数据源 | ✅ 完成 | 已连接 OpenDota + patch_notes，支持 4 种检索 |
| 新增 /query/experimental 端点 | ✅ 完成 | 新路由已创建并测试通过 |
| ExperimentalService | ✅ 完成 | 实现完整 v2.1 数据流 |
| Analyzer 规则推理 | ✅ 完成 | 复用加权公式 + 生成 evidence |
| Formatter 格式化 | ✅ 完成 | 构建标准 MetaReportResponse |
| 端到端测试 | ✅ 完成 | 6 个集成测试全部通过 |

**已实现功能**：
- ✅ `/api/v1/query/experimental` 端点
- ✅ meta_report 完整流程（offlane/carry/mid/support 角色）
- ✅ 规则推理：加权公式计算 meta_score
- ✅ 证据生成：基于阈值生成 supported/partial/weak verdict
- ✅ Critic 审核：Layer 1 规则验证（无证据/不支持信号 → reject）
- ✅ 真实数据：OpenDota API + patch JSON
- ✅ 降级处理：OpenDota 失败时返回空报告

**测试覆盖**：
- `test_experimental_meta_report_flow` - 端到端 meta report
- `test_retriever_fetches_real_data` - Retriever 真实数据获取
- `test_analyzer_generates_evidence` - Analyzer 证据生成逻辑
- `test_critic_validates_evidence` - Critic 审核逻辑
- `test_experimental_team_query_routes_correctly` - 意图路由验证
- `test_experimental_patch_query_routes_correctly` - 意图路由验证

### 📋 Milestone 2：LLM 增强（未开始）

| 任务 | 说明 | 预计工时 |
|------|------|----------|
| LLM provider 抽象 | 统一 OpenAI / Anthropic 接口，按 Agent 分配模型档位 | 2h |
| Orchestrator function calling | LLM 意图解析 + 工具编排 + 重试控制 | 4-5h |
| Analyzer LLM 推理 | claim 生成 + evidence 绑定 + 自然语言 reasons | 3-4h |
| Critic Layer 2 LLM 审核 | 加载 yaml 配置 + LLM 深度审核 | 3-4h |

### 📋 Milestone 3：生产切换（未开始）

| 任务 | 说明 | 预计工时 |
|------|------|----------|
| A/B 测试机制 | 环境变量/header 控制新旧架构切换 | 1h |
| 逐服务迁移 | patch_impact → team_report → meta_report → claim_verification | 2-3h |
| 性能对比 | 延迟、准确度、LLM 成本对比 | 1h |
| 清理旧代码 | 移除旧 6 层 Agent | 1h |

---

## 未完成工作（其他）

### 高优先级

| 任务 | 说明 | 预计工时 |
|------|------|----------|
| 回测脚本 | `eval/backtest.py`，3 个历史版本 top-10 重合度 | 2h |
| Claim Verification 真实化 | 接 patch JSON + OpenDota 数据做证据聚合 | 2h |

### 中优先级

| 任务 | 说明 | 预计工时 |
|------|------|----------|
| LLM provider 抽象 | 统一 OpenAI / Anthropic 接口，按 Agent 分配模型档位 | 2h |
| CAP 集成 | 暴露付费服务、接 CROO Agent Store | 4-6h |
| STRATZ GraphQL | 精确时间过滤 + 单次查询战队 draft 数据 | 半天 |

### 低优先级

| 任务 | 说明 | 预计工时 |
|------|------|----------|
| 前端动态查询 | AskConsole 输入框接入后端路由 | 2h |
| 多角色支持 | 前端支持切换 carry/mid/support 查询 | 1h |
| 数据库持久化 | 报告存档 + 历史查询 | 3h |
| Demo 视频 | 5 分钟录屏 | 2h |

---

## 架构现状

> **当前状态**：v2.1 骨架已建立，新旧架构并存（agents/ 包含新 3 层 + 旧 6 层）。

```
apps/api/
├── app/
│   ├── agents/          # [新 v2.1] orchestrator/analyzer/critic ✅ 骨架完成
│   │   ├── orchestrator.py  # 意图识别完成，LLM 未接入
│   │   ├── analyzer.py      # 工具方法完成，LLM 未接入
│   │   ├── critic.py        # Layer 1 规则完成，Layer 2 未接入
│   │                    # [旧 v2] data/patch/reasoning/verification/report/planner ⚠️ 仍在使用
│   ├── tools/           # [新 v2.1] retriever/formatter ✅ 已建立
│   │   ├── retriever.py     # 类型定义完成，数据连接进行中
│   │   └── formatter.py     # 占位完成
│   ├── config/          # [新 v2.1] ✅ 已建立
│   │   ├── signals.yaml     # 信号阈值配置
│   │   └── critic_rules.yaml # Critic Layer 1 规则
│   ├── api/v1/          # routes + schemas (Pydantic models)
│   ├── core/            # config (pydantic-settings)
│   ├── data/
│   │   ├── mock_data.py # 降级用的静态数据
│   │   └── patches/     # 结构化 patch JSON
│   │       └── 7_41d.json
│   ├── integrations/
│   │   ├── opendota.py  # REST client + 内存缓存 + role mapping
│   │   ├── patch_notes.py  # 本地 JSON 读取 + patch score 计算
│   │   └── stratz.py    # placeholder
│   └── services/        # meta_report / patch_impact / team_report / claim_verification / pricing
└── tests/
```

```
apps/web/                # Next.js 15 + Tailwind + ECharts
├── src/
│   ├── app/page.tsx     # SSR 主页，调后端 4 个 API
│   ├── components/      # 5 个面板组件 + AppShell + AskConsole
│   ├── lib/api.ts       # fetch 封装，失败 fallback 到 mock.ts
│   └── types/report.ts  # TypeScript 类型定义
```

---

## 数据流

> 当前实现（v2 旧架构，仍在使用）：

```
用户请求
  → FastAPI route (async)
    → DataAgent.hero_stats_for_role_async()
      → OpenDotaClient.get_hero_stats_for_role()
        → GET https://api.opendota.com/api/heroStats (1h 缓存)
      → _inject_patch_scores()
        → patch_notes.compute_hero_patch_score("latest")
          → 读取 data/patches/7_41d.json
    → ReasoningAgent.meta_score() (加权公式)
    → VerificationAgent.hero_evidence() (规则判断)
  → 返回 MetaReportResponse JSON
```

> v2.1 新架构（Milestone 1 目标，规则推理）：

```
用户请求
  → /api/v1/query/experimental
    → Orchestrator.plan(query) → OrchestrationPlan (意图识别)
    → Orchestrator.run(plan, handlers)
      → retrieve_meta/patch/team/claim() → EvidenceBundle
      → Analyzer.analyze() → 规则推理 + evidence 打分
      → Critic.review_evidence() → Layer 1 规则审核
      → format_report() → 标准 Response
  → 返回 MetaReportResponse JSON (含 plan trace)
```

> v2.1 终态（Milestone 2 目标，LLM 推理）：

```
用户请求
  → /api/v1/query
    → Orchestrator Agent (LLM function calling)
      → tool: retrieve_*() → EvidenceBundle
      → Analyzer Agent (LLM) → claims + evidence_ids + reasons
      → Critic Agent (Layer 1 规则 + Layer 2 LLM) → pass / reject
          ├─ reject → Orchestrator 决策：补数据 / 重推 / 降级
          └─ pass   → tool: format_report()
  → 返回 MetaReportResponse JSON (含 trace 元数据)
```

---

## 已知限制

1. **Hero pool depth** 使用历史全量数据（≥30 场），非近期真实池；需 STRATZ 或付费 OpenDota key 解决
2. **patch_impact_score** 按 buff/nerf 计数简单加减，不区分改动强度
3. **Role 映射** 依赖 override 表，新英雄需手动添加
4. **前端 SSR** 依赖后端先启动，否则 fallback 到 mock
5. **无 LLM 推理** — reasons / practice_advice 字段为空，meta_score 是纯公式

---

## 文档目录

```
docs/
├── design/              # 产品设计文档
│   ├── MetaMind_MVP_v1.md      # 原始 MVP 设计（完整版，6 Agent）
│   ├── MetaMind_MVP_v2.md      # 工程实施版（6→3，信号制评分）
│   └── MetaMind_MVP_v2.1.md    # ★ 当前版：3 Agent + 2 Tool + Critic 闭环
├── technical/           # 技术文档
│   ├── api.md                # API 接口说明
│   ├── architecture.md       # 系统架构（已对齐 v2.1）
│   └── cap-integration.md    # CAP 集成计划
└── progress/            # 施工进度
    ├── progress_zh.md        # 本文件
    └── progress_en.md        # English version
```
