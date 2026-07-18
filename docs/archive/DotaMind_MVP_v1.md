# DotaMind：Composable Esports Intelligence Agent

## 1. 项目定位

DotaMind 是一个面向电竞游戏的版本情报分析 Agent。

它以 Dota2 为首个支持游戏，通过读取版本更新、天梯数据、职业比赛数据和战队表现，自动生成可验证、可复用、可付费调用的游戏 Meta 分析报告。

与普通数据网站不同，DotaMind 不只是展示“谁胜率高”，而是回答：

- 为什么这个英雄在当前版本变强？
- 版本更新对不同位置有什么影响？
- 哪些英雄值得练？
- 某支职业战队最近为什么表现强势？
- 当前版本的职业比赛趋势是什么？
- 未来短期内可能流行哪些英雄和阵容？

在 CROO Hackathon 语境下，DotaMind 的最终产品形式不是一个单纯网页，而是一个可以被人类用户和其他 Agent 调用的 A2A 情报服务。

---

## 2. 对应 Hackathon 赛道

### 主赛道：Research & Intelligence Agents

DotaMind 提供基于可验证数据源的电竞情报分析服务。

核心输出包括：

- 版本分析报告
- 强势英雄报告
- 职业战队分析报告
- BP 趋势报告
- 英雄推荐报告

每份报告都应包含：

- 数据来源
- 分析过程
- 关键指标
- 推理结论
- 置信度说明

### 副赛道：Data & Verification Agents

DotaMind 同时具备数据校验能力：

- 校验版本信息来源
- 校验英雄胜率、登场率、Ban 率
- 校验职业比赛数据
- 对 Agent 输出进行 evidence check
- 避免生成无来源的游戏结论

---

## 3. 核心问题

当前已有 OpenDota、Dotabuff、STRATZ 等平台可以提供大量 Dota2 数据。

但是它们主要解决的是：

> 数据在哪里？

而不是：

> 数据说明了什么？

用户仍然需要自己完成：

- 对比版本改动
- 查英雄胜率变化
- 查职业比赛 BP
- 判断英雄是否真的变强
- 判断职业队是否适应了版本
- 将数据转化为可执行建议

DotaMind 要解决的问题是：

> 将分散的游戏数据转化为可解释、可验证、可付费调用的电竞情报。

---

## 4. MVP 核心功能

### 功能一：当前版本强势英雄分析

用户输入：

```text
分析当前版本最值得练的三号位英雄。
```

Agent 输出：

```text
当前版本推荐三号位英雄：

1. Beastmaster
推荐理由：
- 当前版本登场率上升
- 高分段胜率稳定
- 职业比赛 BP 率提升
- 适合当前偏快节奏版本

2. Underlord
推荐理由：
- 对线稳定
- 团战容错率高
- 适合克制当前热门物理核心

3. Mars
推荐理由：
- 职业比赛中仍有较高战术价值
- 与当前热门辅助配合度高
```

每个英雄应包含：

- 胜率
- 登场率
- Ban 率
- 高分段表现
- 职业比赛表现
- 版本改动相关性
- 推荐等级

---

### 功能二：版本更新影响分析

用户输入：

```text
7.41d 对 Carry 位有什么影响？
```

Agent 工作流：

```text
读取官方 Patch Notes
→ 抽取英雄 / 装备 / 机制改动
→ 判断受益英雄和受损英雄
→ 查询版本后数据变化
→ 生成影响报告
```

输出包括：

- 版本赢家
- 版本输家
- 受益装备
- 受损打法
- 可能流行的阵容方向
- 对玩家的练习建议

---

### 功能三：职业战队表现分析

用户输入：

```text
分析 Team Spirit 最近为什么强。
```

Agent 工作流：

```text
查询最近职业比赛
→ 统计胜负情况
→ 统计 BP 倾向
→ 分析英雄池
→ 分析版本适应情况
→ 生成战队情报报告
```

输出包括：

- 最近战绩
- 常用英雄
- BP 偏好
- 胜利模式
- 失败模式
- 版本适应评分
- 关键选手表现

---

### 功能四：可被其他 Agent 调用的付费服务

CROO Hackathon 强调 A2A composability 和 Agent commerce，因此 DotaMind 需要暴露可调用服务。

示例服务：

```text
get_meta_report(game, patch, role)
```

用途：

返回某个游戏、某个版本、某个位置的 Meta 报告。

示例：

```json
{
  "game": "dota2",
  "patch": "7.41d",
  "role": "offlane"
}
```

---

```text
get_team_report(game, team_name, time_range)
```

用途：

返回职业战队分析报告。

示例：

```json
{
  "game": "dota2",
  "team_name": "Team Spirit",
  "time_range": "last_30_days"
}
```

---

```text
verify_meta_claim(claim)
```

用途：

校验某个游戏版本判断是否有数据依据。

示例：

```json
{
  "claim": "Beastmaster is one of the strongest offlaners in current patch."
}
```

输出：

```json
{
  "verdict": "partially_supported",
  "evidence": [
    "high pick rate in pro matches",
    "stable win rate in high MMR games"
  ],
  "confidence": 0.76
}
```

---

## 5. Agent 架构设计

### 5.1 Planner Agent

负责理解用户问题，并拆分任务。

示例：

用户问：

```text
当前版本哪些中单最强？
```

Planner 拆解为：

```text
1. 获取当前版本号
2. 查询中单英雄列表
3. 查询天梯数据
4. 查询职业比赛数据
5. 读取版本改动
6. 生成强势指数
7. 输出分析报告
```

---

### 5.2 Patch Agent

负责读取和理解官方版本更新。

输入：

```text
Dota2 patch notes
```

输出：

```json
{
  "patch": "7.41d",
  "changes": [
    {
      "type": "item_change",
      "target": "Mage Slayer",
      "change": "damage reduced",
      "impact": "nerf"
    },
    {
      "type": "item_change",
      "target": "Dagon",
      "change": "recipe cost reduced",
      "impact": "buff"
    }
  ]
}
```

---

### 5.3 Data Agent

负责调用数据源。

MVP 阶段优先接入：

- OpenDota API
- STRATZ API
- 官方 Dota2 Patch Notes

可选接入：

- Liquipedia
- Dotabuff 页面数据
- Steam Web API

Data Agent 获取：

- 英雄胜率
- 英雄登场率
- 英雄 Ban 率
- 职业比赛记录
- 战队胜率
- BP 数据
- 比赛时间
- 版本号

---

### 5.4 Meta Reasoning Agent

负责把数据转化为结论。

它不直接说：

```text
某英雄胜率高，所以强。
```

而是综合判断：

```text
英雄强势指数 =
天梯胜率
+ 高分段登场率
+ 职业比赛 BP 率
+ 版本改动受益程度
+ 克制当前热门英雄能力
+ 阵容适配性
```

示例输出：

```text
Beastmaster 当前版本强度较高，不只是因为胜率上升，
而是因为版本节奏、职业 BP 倾向和高分段登场率同时支持这一判断。
```

---

### 5.5 Verification Agent

负责检查输出结论是否有证据支持。

每个核心结论都应被标记为：

```text
Supported
Partially Supported
Weakly Supported
Unsupported
```

示例：

```text
结论：Beastmaster 是当前版本最强三号位之一。

验证：
- 高分段登场率：支持
- 职业比赛 BP：支持
- 胜率：部分支持
- 版本直接加强：弱支持

最终判断：Partially Supported
置信度：0.76
```

---

### 5.6 Report Agent

负责生成最终报告。

报告类型包括：

- 玩家简版
- 高分段分析版
- 职业战队分析版
- 内容创作者版
- 其他 Agent 调用版 JSON

---

## 6. A2A 可组合性设计

为了符合 CROO Hackathon 要求，DotaMind 不应只是网页应用，还需要成为其他 Agent 可以调用的服务。

### 6.1 可被调用的服务

#### Service 1: Meta Report Service

```text
输入：
game, patch, role

输出：
当前版本该位置强势英雄报告
```

#### Service 2: Team Intelligence Service

```text
输入：
game, team_name, time_range

输出：
职业战队近期表现报告
```

#### Service 3: Patch Impact Service

```text
输入：
game, patch

输出：
版本影响报告
```

#### Service 4: Claim Verification Service

```text
输入：
game-related claim

输出：
判断该说法是否有数据支持
```

---

### 6.2 其他 Agent 如何调用 DotaMind

示例一：内容创作 Agent

```text
内容创作 Agent 调用 DotaMind：
请生成 7.41d 版本三号位分析。

DotaMind 返回结构化情报。

内容创作 Agent 再生成 YouTube 视频脚本。
```

示例二：战队训练 Agent

```text
训练 Agent 调用 DotaMind：
请分析 Team Falcons 最近 30 天 BP 倾向。

DotaMind 返回 BP 报告。

训练 Agent 基于报告生成训练计划。
```

示例三：投注风险分析 Agent

```text
风险分析 Agent 调用 DotaMind：
请分析 Team Spirit vs Falcons 的版本适应度差异。

DotaMind 返回双方战队情报。

风险分析 Agent 再进行风险判断。
```

注意：MVP 不直接做博彩预测，避免合规风险。只提供公开比赛情报分析。

---

## 7. 商业化设计

CROO 的核心问题是：

> You’ve built an Agent that works. How do you make it earn?

因此 DotaMind 需要设计付费能力。

### 7.1 服务定价

MVP 阶段可以设置三类调用：

```text
Basic Meta Report：0.1 USDC
Team Intelligence Report：0.3 USDC
Deep Patch Impact Report：0.5 USDC
```

### 7.2 付费对象

- 玩家
- 内容创作者
- 电竞自媒体
- 战队分析师
- 其他 Agent
- 游戏社区 Bot

### 7.3 为什么其他 Agent 会付费调用？

因为 DotaMind 提供的是垂直数据处理能力。

其他 Agent 不需要自己接 OpenDota、STRATZ、Patch Notes，也不需要自己做版本分析，只需要调用 DotaMind 的结果。

---

## 8. 数据源设计

### 8.1 官方版本数据

来源：

```text
Dota2 Official Patch Notes
```

用途：

- 获取版本号
- 获取英雄改动
- 获取装备改动
- 获取机制改动

---

### 8.2 OpenDota

用途：

- 公共比赛数据
- 职业比赛数据
- 英雄数据
- 玩家数据
- 比赛详情

---

### 8.3 STRATZ

用途：

- 高级比赛数据
- BP 数据
- 英雄趋势
- 更细粒度统计

---

### 8.4 Liquipedia

用途：

- 赛事信息
- 队伍名单
- 赛程
- 战队背景

---

## 9. 数据处理流程

### 9.1 英雄强势指数

MVP 可以先定义一个简单公式：

```text
Meta Score =
0.30 * win_rate_score
+ 0.25 * pick_rate_score
+ 0.20 * pro_presence_score
+ 0.15 * patch_impact_score
+ 0.10 * trend_score
```

说明：

- win_rate_score：英雄胜率
- pick_rate_score：登场率
- pro_presence_score：职业比赛 BP 存在感
- patch_impact_score：版本改动影响
- trend_score：最近趋势变化

---

### 9.2 战队版本适应分

```text
Patch Adaptation Score =
0.30 * recent_win_rate
+ 0.25 * meta_hero_usage
+ 0.20 * draft_flexibility
+ 0.15 * hero_pool_depth
+ 0.10 * opponent_strength
```

用于分析：

- 哪支队更适应当前版本
- 哪支队英雄池更贴近版本
- 哪支队 BP 更灵活

---

### 9.3 输出置信度

```text
Confidence =
数据完整度
+ 数据新鲜度
+ 多源一致性
+ 样本量充足度
```

示例：

```text
Confidence: 0.82

Reason:
- OpenDota 和 STRATZ 数据趋势一致
- 样本量充足
- 数据来自当前版本
```

---

## 10. 技术栈

### Frontend

```text
Next.js
Tailwind CSS
ECharts
```

### Backend

```text
FastAPI
Python
```

### Agent Framework

```text
LangGraph
或
OpenAI Agents SDK
```

### LLM

```text
GPT-4.1
GPT-5
Qwen
```

### Data

```text
OpenDota API
STRATZ GraphQL API
Dota2 Patch Notes
```

### Database

```text
PostgreSQL
Redis
```

### Optional

```text
Neo4j，用于 Patch-Hero-Item-Meta 知识图谱
```

---

## 11. MVP 页面设计

### 页面一：首页

内容：

```text
DotaMind
Composable Esports Intelligence Agent

Ask anything about game meta, patch impact, and pro team performance.
```

输入框示例：

```text
Analyze the strongest offlane heroes in current Dota2 patch.
```

---

### 页面二：Meta Report Dashboard

展示：

- 推荐英雄排行榜
- 胜率
- 登场率
- 职业 BP 率
- Meta Score
- Confidence
- 分析解释

---

### 页面三：Patch Impact Report

展示：

- 当前版本变化摘要
- 版本赢家
- 版本输家
- 装备变化影响
- 阵容趋势

---

### 页面四：Team Intelligence Report

展示：

- 战队近期战绩
- 常用英雄
- BP 偏好
- 版本适应度
- 风险点

---

### 页面五：Agent API / CAP Service 页面

展示：

```text
This agent can be called by other agents.

Available services:
- get_meta_report
- get_team_report
- get_patch_impact
- verify_meta_claim
```

并展示价格：

```text
Basic Report: 0.1 USDC
Team Report: 0.3 USDC
Deep Report: 0.5 USDC
```

---

## 12. Demo 设计

### Demo 1：玩家视角

用户输入：

```text
I play position 3. Which heroes should I practice in the current patch?
```

Agent 输出：

- 三个推荐英雄
- 每个英雄的推荐理由
- 数据支持
- 练习建议

---

### Demo 2：版本分析视角

用户输入：

```text
How does patch 7.41d affect the current Dota2 meta?
```

Agent 输出：

- 版本核心变化
- 受益英雄
- 受损英雄
- 职业比赛趋势
- 未来两周预测

---

### Demo 3：A2A 视角

另一个 Agent 调用：

```json
{
  "service": "get_meta_report",
  "game": "dota2",
  "patch": "latest",
  "role": "offlane"
}
```

DotaMind 返回：

```json
{
  "report_type": "meta_report",
  "game": "dota2",
  "patch": "latest",
  "role": "offlane",
  "top_heroes": [
    {
      "hero": "Beastmaster",
      "meta_score": 86,
      "confidence": 0.78,
      "reason": "Strong pro presence and positive high-MMR trend."
    }
  ],
  "sources": [
    "OpenDota",
    "STRATZ",
    "Dota2 Patch Notes"
  ]
}
```

---

## 13. 开发优先级

### Day 1-2：数据源接入

- 接入 OpenDota
- 接入 Dota2 Patch Notes
- 建立英雄基础数据表

### Day 3-5：核心分析逻辑

- 实现 Meta Score
- 实现 Patch Impact 判断
- 实现基础 Team Report

### Day 6-8：Agent 工作流

- Planner
- Data Agent
- Patch Agent
- Reasoning Agent
- Verification Agent

### Day 9-11：前端展示

- 首页
- Meta Report Dashboard
- Patch Impact Dashboard
- Team Report Dashboard

### Day 12-14：CAP / A2A 集成

- 暴露 Agent 服务
- 设置价格
- 接入 CAP
- 实现其他 Agent 可调用接口

### Day 15：Demo 与 README

- 录制 5 分钟 Demo
- 完善 README
- 补充架构图
- 补充调用示例

---

## 14. README 必须强调的点

根据 Hackathon 要求，README 应包含：

- 项目简介
- 解决的问题
- Agent 工作流
- CAP 集成方式
- 使用了哪些 SDK 方法
- 如何运行
- 如何调用 Agent
- 如何收费
- 数据来源
- Demo 链接
- 开源协议

建议协议：

```text
MIT License
```

或：

```text
Apache 2.0
```

---

## 15. 评审标准对应策略

### Technical Execution 30%

对应策略：

- 稳定的数据源接入
- 可运行的前后端
- CAP 集成
- Agent 可被调用
- 至少完成 10 次以上真实 CAP order 测试

---

### A2A Composability 25%

对应策略：

- 不只做网页
- 暴露 3-4 个可调用服务
- 展示其他 Agent 调用 DotaMind 的例子
- 输出结构化 JSON
- 让 DotaMind 成为其他 Agent 的依赖

---

### Innovation 20%

对应策略：

- 不是普通 Dota 查询工具
- 强调 Patch → Data → Reasoning → Verification
- 做“电竞情报服务”
- 做 Meta 预测和版本解释

---

### Usability & Real Adoption 15%

对应策略：

- 面向真实 Dota2 玩家
- 面向内容创作者
- 面向电竞分析师
- 输出可以直接使用的报告
- 支持英文查询，后续可支持中文

---

### Presentation 10%

对应策略：

- 5 分钟 Demo 清晰展示
- README 可复现
- 展示 CAP 调用记录
- 展示 Agent Store 上架页面
- 展示价格和服务说明

---

## 16. 最终提交形式

最终提交应包括：

```text
1. GitHub Repo
2. README.md
3. Demo Video，5 分钟以内
4. Agent Store Listing
5. CAP Integration Notes
6. DoraHacks BUIDL 页面
```

---

## 17. 项目一句话介绍

DotaMind is a composable esports intelligence agent that turns patch notes, match data, and pro team statistics into verifiable, paid game meta reports for humans and other agents.

中文：

DotaMind 是一个可组合的电竞情报 Agent，它将版本更新、比赛数据和职业战队表现转化为可验证、可付费调用的游戏 Meta 分析报告。

---

## 18. 核心卖点

普通数据网站告诉你：

```text
谁胜率高。
```

DotaMind 告诉你：

```text
为什么他强，
证据是什么，
这个判断是否可靠，
以及其他 Agent 如何付费调用这份情报。
```

---

## 19. 最终产品形态

DotaMind 的最终产品不是单一网页，而是三部分组成：

```text
Web Dashboard
+
Callable Agent Service
+
CAP Paid Service
```

### 19.1 Web Dashboard

面向人类用户，提供可视化分析体验。

### 19.2 Callable Agent Service

面向其他 Agent，提供结构化 API / A2A 服务。

### 19.3 CAP Paid Service

面向 CROO Agent Store，实现发现、调用、付费和结算。

---

## 20. MVP 边界

MVP 阶段不做：

- 多游戏支持
- 复杂胜负预测
- 博彩建议
- 深度 replay 解析
- 完整图数据库

MVP 阶段重点做：

- Dota2 单游戏
- 版本分析
- 英雄推荐
- 战队分析
- 数据校验
- CAP / A2A 集成
