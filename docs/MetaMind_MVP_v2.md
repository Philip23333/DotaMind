# MetaMind MVP 设计文档 v2（工程实施版）

本版本仅替换 v1 中的三块：**Agent 架构（原第 5 节）**、**数据源设计与风险（原第 8 节）**、**核心算法（原第 9 节）**。其余章节（定位、商业化、页面、时间线等）继续沿用 v1，但建议按本版本的取舍重新裁剪。

设计原则：
- **可证伪优先于可炫耀**：宁可输出"证据不足"，不输出无依据的分数。
- **缓存优先于实时**：Meta 报告按 (patch, role) 维度缓存，调用时优先命中。
- **少即是多**：Agent 数量、数据源、子分量都按"砍到不能再砍"的标准设计。

---

## 1. Agent 架构（替换原第 5 节）

### 1.1 从 6 个 Agent 精简为 3 个

v1 的六层架构（Planner / Patch / Data / Reasoning / Verification / Report）对 15 天 MVP 过重，且 Planner 在固定 4 个服务下退化成 if-else。本版收敛为三层：

```
Retriever  →  Analyzer  →  Formatter
（取数）      （推理+核验）    （成稿）
```

服务路由由一个**纯函数 router**完成，不算 Agent：

```python
def route(request):
    # request.service ∈ {meta_report, patch_impact, team_report, verify_claim}
    return SERVICE_PIPELINE[request.service]
```

### 1.2 三个 Agent 的职责

**Retriever Agent**

- 唯一职责：把 (game, patch, role, team, claim) 解析成一组数据查询，返回**统一格式的 Evidence Bundle**。
- 内部封装所有数据源差异（OpenDota / STRATZ / Patch Notes / 缓存）。
- 不调用 LLM，纯代码 + 结构化抽取（patch notes 抽取另起一个**离线**任务，见第 2 节）。
- 输出 schema 固定（见 1.4）。

**Analyzer Agent**

- 输入：Evidence Bundle。
- 单次 LLM 调用，prompt 内同时完成 reasoning 与 verification（v1 拆成两个 Agent 是不必要的，二者共享同一份证据，分开会重复消耗 token）。
- 强制结构化输出：`claims[]`，每个 claim 必须挂上 `evidence_ids[]` 和 `verdict ∈ {supported, partial, weak, unsupported}`。
- **没有挂证据的 claim 在后处理阶段直接丢弃**，从机制上杜绝幻觉。

**Formatter Agent**

- 不调用 LLM（或只用最便宜的小模型做润色）。
- 把 Analyzer 输出渲染成三种形态：human markdown / dashboard JSON / A2A response JSON。

### 1.3 调用链与成本

| 服务 | LLM 调用次数 | 外部 API 调用 | 目标 P50 延迟 | 缓存键 |
|---|---|---|---|---|
| meta_report | 1 | 2-4 | < 8s | (patch, role) |
| patch_impact | 1 | 1-2 | < 6s | (patch) |
| verify_claim | 1 | 1-3 | < 10s | claim hash |
| team_report | 1 | 3-5 | < 12s | (team, week) |

**强制缓存**：Retriever 出口和 Analyzer 出口都落 Redis，TTL 分别为 1h 和 6h。Patch Notes 抽取结果落 Postgres，TTL 直到下个版本。

成本估算（单次 cache miss，GPT-4 级别模型）：
- 输入 token ~3-5k（Evidence Bundle 已结构化，避免塞原始 JSON）
- 输出 token ~1-2k
- 单次 LLM 成本约 $0.03-0.08

定价 0.1 USDC 起的 Basic Report 在缓存命中率 > 60% 时才有正毛利，**这一条必须写进 README 的限制说明**。

### 1.4 Evidence Bundle 统一 schema

所有 Retriever 出口都符合此结构，Analyzer 只认这一个 schema：

```json
{
  "request": {"service": "meta_report", "patch": "7.41d", "role": "offlane"},
  "evidences": [
    {
      "id": "e1",
      "source": "opendota",
      "kind": "hero_winrate",
      "subject": "beastmaster",
      "value": {"winrate": 0.534, "sample": 12480, "bracket": "ancient+"},
      "fetched_at": "2026-06-12T03:00:00Z",
      "freshness_days": 2
    },
    {
      "id": "e2",
      "source": "patch_notes",
      "kind": "hero_change",
      "subject": "beastmaster",
      "value": {"raw": "Boar damage increased 28→32", "polarity": "buff"},
      "patch": "7.41d"
    }
  ],
  "missing": ["pro_pickrate"],
  "data_quality": {"completeness": 0.75, "freshness_days_avg": 2.1}
}
```

`missing` 字段是工程上的关键：Analyzer 看到 `missing` 非空时，必须在结论里显式声明"X 维度数据缺失"，而不是装作完整。

---

## 2. 数据源设计与风险（替换原第 8 节）

### 2.1 分级接入策略

不再"三个源都 Day 1-2 接入"。按**必需 / 增强 / 可选**分级：

| 源 | 等级 | MVP 用途 | 风险 | 降级方案 |
|---|---|---|---|---|
| OpenDota REST | **必需** | 英雄胜率/登场率、pro matches 列表 | rate limit 60/min，pro 数据有延迟 | API key 提升到 1200/min；本地 SQLite 镜像核心表 |
| Dota2 Patch Notes | **必需** | 版本改动结构化 | 无官方 API，HTML 易变 | **Day 1 只手工录入当前 1 个版本的 JSON**，自动抽取放 Day 6+ |
| STRATZ GraphQL | 增强 | BP 率、高分段细分 | schema 变动、需 token、严格 rate limit | 缺失时 `missing` 字段标注，Analyzer 不强依赖 |
| Liquipedia | 可选 | 战队名单/赛程 | wiki 结构不稳定 | team_report 服务可整体延后 |
| Dotabuff 抓取 | **不接入** | — | ToS 风险 | 不做 |

### 2.2 Patch Notes 抽取：分两阶段

v1 把"读 Patch Notes"轻描淡写带过，实际是个独立子项目。本版拆分：

**阶段 A（Day 1-2，必做）**：人工把当前主版本（如 7.41d）转写为结构化 JSON，schema 固定为：

```json
{
  "patch": "7.41d",
  "released_at": "2025-xx-xx",
  "changes": [
    {"target_type": "hero", "target": "beastmaster",
     "field": "boar_damage", "from": 28, "to": 32, "polarity": "buff"},
    {"target_type": "item", "target": "dagon",
     "field": "recipe_cost", "polarity": "buff", "raw": "..."}
  ]
}
```

**阶段 B（Day 6+，可选）**：写一个**离线**抽取脚本（不在请求路径上），用 LLM 把新版本 HTML 转成上述 JSON，人工 review 后入库。**永远不在用户请求中实时抽取 patch notes**。

### 2.3 失败时的输出形态（v1 缺失的关键设计）

任何服务在数据不足时，**必须返回结构化的"无法判断"，而不是编造**：

```json
{
  "verdict": "insufficient_data",
  "reason": "STRATZ pro pickrate unavailable; OpenDota sample < 500",
  "partial_evidence": [...],
  "confidence": 0.0
}
```

这一行为对 Verification 赛道是加分项，对评委来说也是诚意展示。

### 2.4 速率与配额护栏

- 所有外部调用走统一 `http_client`，内置 token bucket。
- 每个源单独配额，**优先消耗在 cache miss 的请求上**，缓存预热走低优先级队列。
- Postgres 落一张 `api_call_log`，便于 demo 时展示"我们调用了 X 次外部 API，命中缓存 Y 次"。

---

## 3. 核心算法（替换原第 9 节）

### 3.1 放弃手工加权公式

v1 的 `Meta Score = 0.30*winrate + 0.25*pickrate + ...` 没有 ground truth、没有回测、子分量自身也未定义，是"伪科学"。本版**完全删除标量打分**，改为**证据聚合 + LLM 判断**。

### 3.2 新流程：Signal → Evidence → Verdict

**Step 1. Signal 抽取（确定性代码，无 LLM）**

对每个候选英雄/战队/版本变化，从 Evidence Bundle 中抽出**布尔或分级信号**，每个信号有明确阈值：

| Signal | 判据 | 取值 |
|---|---|---|
| `winrate_high` | high-MMR winrate ≥ 53% 且 sample ≥ 500 | true / false / unknown |
| `winrate_trend_up` | 近 7 天 winrate − 上 7 天 ≥ +1.5pp | true / false / unknown |
| `pickrate_rising` | 登场率周环比 ≥ +20% | true / false / unknown |
| `pro_present` | 最近 30 天 pro 比赛 BP 率 ≥ 15% | true / false / unknown |
| `direct_buff` | 当前版本有 polarity=buff 的改动 | true / false |
| `indirect_buff` | 克制英雄被 nerf / 协同英雄被 buff | true / false |

阈值写在 `config/signals.yaml`，**评委可以直接看到所有阈值**，比黑箱权重透明得多。

**Step 2. LLM 判读（Analyzer Agent）**

把信号矩阵 + 原始证据交给 LLM，prompt 强制要求：

- 只能用提供的 evidence_id 作为论据；
- 输出每条 claim 的 verdict ∈ {supported, partial, weak, unsupported}；
- 任何"强势"判断必须至少 2 个独立来源信号支持，否则降级为 partial。

**Step 3. Confidence（替代 v1 的拍脑袋公式）**

confidence 不是连续浮点，而是**离散等级**，由确定性规则计算：

```
high   : ≥3 个 supported 信号 且 data_quality.completeness ≥ 0.8
medium : ≥2 个 supported 信号 且 completeness ≥ 0.6
low    : 仅 1 个支持信号 或 completeness < 0.6
none   : 无支持信号 → 输出 insufficient_data
```

这个分级**可被任何人手动复现**，这是 Verification Agent 赛道的核心要求。

### 3.3 可回测：选一个最小 ground truth

为了不让算法"自说自话"，定义一个简单回测：

- **任务**：给定 patch P 发布后第 1 周的数据，预测"该版本 top 10 offlane 英雄"。
- **Ground truth**：patch P 后第 4 周的实际 high-MMR pickrate top 10。
- **指标**：top-10 重合数（0-10）。
- **Baseline**：直接按上周 winrate 排序。
- **目标**：MetaMind 的输出 ≥ baseline + 1。

回测脚本放 `eval/backtest.py`，跑 3 个历史版本即可，结果写进 README。**这一条是 v1 完全缺失但对 Technical Execution 评分至关重要**的部分。

### 3.4 战队适应度：同样改为信号制

放弃 `Patch Adaptation Score = 0.30*... + 0.25*...`，改为四个布尔信号：

- `uses_meta_heroes`：最近 10 场中 meta top-20 英雄占比 ≥ 40%
- `recent_form_good`：最近 10 场胜率 ≥ 55%
- `draft_diverse`：英雄池 ≥ 25 个
- `beat_strong_opponents`：击败过至少 1 支 top-tier 战队

输出"4 项中满足 N 项 + 证据列表"，不输出 0-100 分。

---

## 4. 对原文档其他章节的连带修改建议

- **第 11 节页面**：砍到 2 个 Dashboard（Meta + Patch），Team Report 仅作为 A2A 服务暴露，不做 UI。
- **第 13 节时间线**：Day 1-2 只接 OpenDota + 手工 patch JSON；STRATZ 推到 Day 6；Day 12-13 必须留给回测和缓存调优，不能全压到 CAP 集成。
- **第 20 节 MVP 边界**：明确加一条"不实时抽取 patch notes"。
- **README**：必须包含"已知限制"章节，写明缓存窗口、数据延迟、回测分数。

---

## 5. 与 v1 的差异速查

| 维度 | v1 | v2 |
|---|---|---|
| Agent 数 | 6 | 3 |
| 评分方式 | 加权浮点公式 | 信号布尔 + LLM 判读 |
| Confidence | 拍脑袋小数 | 4 级离散规则 |
| Patch Notes | "读取" 一句带过 | 手工 JSON + 离线抽取分阶段 |
| 数据源失败 | 未定义 | `insufficient_data` 强制结构 |
| 回测 | 无 | 3 版本 top-10 重合度 |
| 缓存 | 未提 | Redis + Postgres 双层，定价依赖命中率 |

