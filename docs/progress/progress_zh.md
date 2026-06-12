# MetaMind 施工进度文档

> 最后更新：2026-06-12（v2.1 架构定稿）

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

## 未完成工作

### 高优先级

| 任务 | 说明 | 预计工时 |
|------|------|----------|
| **v2.1 骨架重构** | `agents/` → orchestrator/analyzer/critic；`tools/` → retriever/formatter | 1 天 |
| Orchestrator Agent | LLM function calling，意图解析 + 工具编排 + 重试控制 | 4-5h |
| Analyzer Agent | 单例 LLM，4 种 task_type 共用，强制 evidence 绑定 | 3-4h |
| Critic Agent | 双层审核（规则 yaml + LLM），pass/reject + reasons | 3-4h |
| signals.yaml | 信号阈值配置（v2 第 3.2 节定义） | 1-2h |
| critic_rules.yaml | Critic Layer 1 规则（evidence_binding / freshness / sample_size 等） | 1-2h |
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

> v2.1 是设计目标，下面的目录结构是**当前**的（v2 部分迁移完成，agents/ 仍是旧 6 层布局）。

```
apps/api/
├── app/
│   ├── agents/          # [当前] data/patch/reasoning/verification/report/planner
│   │                    # [v2.1 目标] orchestrator/analyzer/critic
│   ├── tools/           # [v2.1 目标] retriever/formatter (待建)
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
│   ├── config/          # [v2.1 目标] signals.yaml / critic_rules.yaml
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

> 当前实现（v2 部分迁移）：

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

> v2.1 目标流（待实现）：

```
用户请求
  → FastAPI route → Orchestrator Agent (LLM 意图解析)
    → tool: retrieve_meta()  → EvidenceBundle
    → Analyzer Agent (LLM)   → claims + evidence_ids
    → Critic Agent (规则+LLM) → pass / reject
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
