# DotaMind V3.3-3：Valve 静态游戏目录与查询工具

> 状态：A-E 已完成并于 2026-08-10 收口。正式 committed Catalog、Runtime
> Repository/resolver、六个查询工具、EvidenceGraph、Controller/Answer 规则和真实
> 快照验收均已实现；请求期不访问 Valve，也没有旧 YAML 或第三方 fallback。
>
> 本阶段建立在 V2.5 constrained tool calling、V3.2 Agent Runtime 和 V3.3-2
> Chat Run 之上。它新增的是可审计的官方静态游戏数据能力，不改变 Graph 路由语义、
> Chat Run 生命周期或 PostgreSQL/Redis 职责。

更新日期：2026-08-07

## 1. 背景

设计启动时，仓库通过 `scripts/sync_game_data.py` 离线读取 Valve Dota 2 Datafeed，仅生成：

- `app/data/heroes/dota2_heroes.yaml`：英雄 ID、内部名、中英文名和中文别名；
- `app/data/patches/*.json`：版本、英雄、技能和物品改动记录。

运行时 `resolve_hero` 使用本地英雄快照，但尚未提供以下当前版本静态事实：

- 英雄基础属性和成长属性；
- 攻击距离、攻击间隔、护甲、移速、视野等战斗属性；
- 英雄技能描述、等级数值、冷却、耗蓝、先天技能、神杖和魔晶信息；
- 10/15/20/25 级天赋树；
- 物品价格、属性、主动/被动效果、冷却、耗蓝、配方和中立物品等级；
- 中文/英文物品名称解析。

STRATZ 和 OpenDota 继续负责比赛统计、胜率、使用率和样本数据。英雄、技能、天赋和
物品的规则定义应来自 Valve 官方数据，不能从第三方统计页面反推。

## 2. 目标与非目标

### 2.1 目标

- 扩展现有离线同步流程，从 Valve Dota 2 Datafeed 生成可审核的双语静态目录快照。
- 对英雄、技能、天赋和物品数据建立稳定、版本化的内部 schema。
- 在同步阶段解析 Valve 本地化文本和数值占位符，运行时不处理原始网站格式。
- 运行时只读取仓库内快照，不对 Valve、STRATZ 或 OpenDota 发起静态目录 HTTP 请求。
- 提供英雄属性、技能、天赋树、物品解析和物品详情工具。
- 将工具输出转换为 EvidenceGraph evidence，并由现有 `natural_language_answer` 回答。
- 保持 `intent` 仅为语义标签；执行仍完全由验证后的 `tool_calls` 决定。
- 让回答明确公开目录的版本、同步时间和数据来源。

### 2.2 非目标

- 不实现热门出装、加点率、天赋选择率或胜率比较；这些属于比赛统计能力。
- 不把“物品定义”扩展成“推荐某英雄出什么装备”。
- 不抓取 STRATZ 英雄属性、技能或物品页面。
- 不在请求路径实时调用 Valve Datafeed。
- 不引入 OpenDota constants、社区 Wiki 或第三方仓库作为静态事实 fallback。
- 不在本阶段实现 Dota 客户端 VPK 导入；Datafeed 缺失或无法规范化时直接使同步失败。
- 不增加图片下载、英雄/技能/物品卡片或新的前端页面。
- 不新增固定 intent pipeline、专用 API endpoint 或第二套 Agent 路径。
- 不改变现有 Chat Run、Session、PostgreSQL、Redis、幂等或恢复语义。

## 3. 数据权威与运行时边界

### 3.1 数据源优先级

V3.3-3 的唯一自动同步源是 Valve 官方 Dota 2 Datafeed：

| 数据 | Endpoint | 用途 |
| --- | --- | --- |
| 英雄列表 | `/datafeed/herolist` | 英雄 ID、内部名、本地化名 |
| 英雄详情 | `/datafeed/herodata?hero_id=...` | 属性、技能、天赋和描述 |
| 技能列表/详情 | `/datafeed/abilitylist`、`/datafeed/abilitydata` | 技能目录和独立详情校验 |
| 物品列表/详情 | `/datafeed/itemlist`、`/datafeed/itemdata` | 物品目录、详情和配方 |
| 版本列表 | `/datafeed/patchnoteslist` | 给目录快照标记当前版本 |

每次同步同时请求 `english` 和 `schinese`，使用数值 ID 和内部名关联，不用本地化文本作
主键。官方网页和客户端 VPK 可以人工核查，但不进入本阶段自动 fallback 链路。

### 3.2 同步与运行时职责

```text
Valve Datafeed
  -> offline sync transport
  -> normalize + validate
  -> reviewed committed snapshots
  -> runtime CatalogRepository
  -> deterministic Agent tools
  -> EvidenceGraph
  -> Answer + Critic
```

- 同步命令是唯一允许访问 Valve Datafeed 的目录更新入口。
- 同步失败不得覆盖已有有效快照；写文件前必须完成完整内存校验。
- 运行时启动时加载并验证快照；文件缺失或 schema 非法时 fail-fast。
- Tool handler 只查询内存中的只读目录，不包含 HTTP、缓存回源或第三方 fallback。
- 快照是 committed runtime data，不是可随意删除的 cache。

## 4. 快照和领域模型

### 4.1 文件布局

目标布局：

```text
apps/api/app/data/catalog/
  manifest.json
  dota2_heroes.json
  dota2_abilities.json
  dota2_items.json
  sync_audit.json
```

旧 `heroes/dota2_heroes.yaml` 及其 resolver/生成路径在 Catalog 接管默认 registry 后删除，
不保留第二套英雄主数据。中文人工别名继续保留为独立 overlay，在同步时写入 Catalog，
但不写回 Valve 记录。

### 4.2 CatalogManifest

```json
{
  "schema_version": 1,
  "game": "dota2",
  "patch": "7.xx",
  "generated_at": "UTC timestamp",
  "locales": ["english", "schinese"],
  "sources": ["Valve Datafeed endpoint templates"],
  "entity_counts": {
    "heroes": 0,
    "abilities": 0,
    "items": 0
  }
}
```

`generated_at` 表示同步时间，不声称是 Valve 数据自身的发布时间。`patch` 来自最新
`patchnoteslist` 记录，用于回答披露和审计；如果无法确定版本，整个同步失败。

### 4.3 HeroCatalogRecord

至少保存：

- `hero_id`、`internal_name`、`name_en`、`name_zh`、人工 aliases；
- `primary_attribute`、complexity、attack capability、role levels；
- strength/agility/intelligence 的 base 和 gain；
- damage、attack rate/range、projectile speed、armor、magic resistance；
- movement speed、turn rate、day/night sight、health/mana 和 regen；
- 有序 `ability_ids`；
- 四个 `TalentTier`，等级固定为 10/15/20/25，每级 left/right 各一个 talent ID。

### 4.4 AbilityCatalogRecord

至少保存：

- `ability_id`、`internal_name`、`name_en`、`name_zh`；
- 双语 description、lore、notes、Scepter、Shard 文本；
- behavior、target team/type、damage/immunity/dispellable metadata；
- max level、cast range/point、channel time、cooldown、duration、damage、mana/health cost；
- 结构化 special values；
- `is_innate`、Scepter/Shard granted/upgrade flags；
- 所属 hero IDs；天赋技能另标记 `is_talent=true`。

### 4.5 ItemCatalogRecord

至少保存：

- `item_id`、`internal_name`、`name_en`、`name_zh`、aliases；
- 双语 description、lore 和 notes；
- price、quality、stock、initial charges、neutral tier；
- behavior、target、cooldown、duration、mana/health cost 和 special values；
- recipe component IDs、可合成目标 IDs；
- `is_recipe`、`is_neutral`、`is_purchasable` 等规范化分类。

### 4.6 CatalogSyncAudit

`sync_audit.json` 是仅供开发者审查的同步产物，不由 Runtime Catalog 加载，也不进入工具输出。
它至少保存与 manifest 一致的 patch、generated_at，以及被审核排除实体的：

- entity type、数值 ID、内部名和 `legacy_or_unclassified` 分类；
- 排除原因、官方状态证据及来源 endpoint；
- 官方返回的原始双语描述和未解析 token。

manifest 的 entity count 只统计可以向用户展示的运行时目录实体。审计条目不得同时存在于
运行时目录；重复条目、patch/time 不一致或排除实体仍在运行时目录都使同步失败。

## 5. 规范化规则

### 5.1 双语合并

- 以 Valve 数值 ID 为主键；内部名用于一致性校验。
- English 和 Simplified Chinese 的同 ID 记录必须存在且内部名一致。
- 中文字段缺失时不得静默回退到英文；同步报告明确失败字段。
- 人工 hero/item alias 仅影响 resolver，不改变官方名称和描述。

### 5.2 富文本清理

- 将 Valve 描述中的允许 HTML 标签转换为稳定纯文本段落和标题。
- 解码 HTML entity，统一换行和空白。
- 不把未经清理的 HTML 交给 ToolResult 或 Answer LLM。
- 原始描述可作为快照内部审计字段保留，但不进入默认工具输出。

### 5.3 数值占位符

必须支持两类当前 Datafeed 占位符：

```text
%damage_bonus%
{s:value}
{s:bonus_AbilityCooldown}
```

解析顺序：

1. 当前 ability/item/talent 的 `special_values`；
2. 英雄全部技能 `special_values[].bonuses[]` 中以 talent internal name 关联的 bonus；
3. 对同一 talent 的多个 bonus 分别按字段名替换；
4. 生成结构化数值和已渲染双语文本。

同步完成后，所有默认展示字段必须没有未解析 token。发现 token 时生成稳定校验错误并中止
写入，不猜测数值，也不在运行时回源。

### 5.4 天赋树

- 每个英雄必须规范化为 10/15/20/25 四层，每层恰好两个选择。
- Datafeed 顺序只在同步器有明确验证时使用；输出模型显式保存 `level/left/right`。
- talent ID 必须存在于 ability catalog，且 talent bonus 关联必须能解析。
- 英雄技能列表和天赋列表分开，避免 Answer 把天赋当普通技能。

### 5.5 配方图

- item list 中的 recipe 关系规范化为 component IDs 和 upgrade target IDs。
- 所有引用 ID 必须存在；循环、悬空引用或重复边使同步失败。
- 图纸项和最终物品是不同实体，resolver 默认优先最终物品，用户明确说“图纸”时才匹配图纸。
- Runtime repository 可以从图纸 ID 或 edge 的成品 ID 查询同一条配方边，并返回深拷贝。
- `item_recipe` 保留图纸、组件和升级目标的双语身份、价格、可展示属性，以及组件、图纸、
  计算总价与成品价格的一致性明细；不得用成品记录中缺少图纸 ID 推断“无图纸”。

### 5.6 已审核的当前目录排除

当 Valve Datafeed 仍列出一个没有可用状态字段、无法完整渲染效果、且没有商店/中立等级/
配方关系等当前获取路径的实体时，可以将其从默认运行时目录排除并写入 `sync_audit.json`。
排除必须限定到已人工审核的精确数值 ID 和内部名，并校验双语身份、未解析 token、状态字段、
special value 字段及配方关系的已知形状；任一上游形状发生变化都必须 fail-fast，要求重新审核，
不得把该规则扩展成对其他英雄、技能或物品的通用猜测。审计记录保留原始描述和 token 供开发者
查看，但 resolver、工具和 Answer 都不得向用户展示残缺效果。

## 6. Runtime Catalog 与 Resolver

新增只读 `DotaCatalogRepository`：

```text
get_hero(hero_id)
get_ability(ability_id)
get_hero_abilities(hero_id)
get_hero_talent_tree(hero_id)
resolve_item(query)
get_item(item_id)
get_item_recipe_edges(item_id)
```

要求：

- 使用 Pydantic 模型加载三个快照和 manifest。
- 服务构造期一次加载，handler 不重复读盘。
- 返回副本或不可变 DTO，调用者不能修改全局目录。
- item resolver 与现有 hero resolver 使用相同的 exact/fuzzy/ambiguous/not_found 语义。
- resolver 索引包含中英文名、去前缀内部名和人工 aliases。
- 不通过历史 Turn 直接复用 hero/item ID；当前计划仍必须执行 resolver。

当前 `resolve_hero` 的工具注册从 `stratz_tools.py` 移入新的
`dota_catalog_tools.py`，保持工具名、输入和 `data.hero.hero_id` 输出路径不变。迁移完成后不保留
两份注册或兼容 handler。

## 7. Tool 与 Evidence 合同

### 7.1 工具目录

| Tool | 输入 | 稳定输出路径 | Evidence | Mandatory |
| --- | --- | --- | --- | --- |
| `resolve_hero` | `query` | `data.hero.hero_id` | `hero_identity` | `hero_identity` |
| `dota.hero_attributes` | `hero_id` | `data.hero`, `data.attributes`, `data.combat` | `hero_attributes` | `hero_attributes` |
| `dota.hero_abilities` | `hero_id` | `data.hero`, `data.abilities` | `hero_ability` | `hero_ability` |
| `dota.hero_talent_tree` | `hero_id` | `data.hero`, `data.talent_tree` | `hero_talent_tree` | `hero_talent_tree` |
| `resolve_item` | `query` | `data.item.item_id` | `item_identity` | `item_identity` |
| `dota.item_info` | `item_id` | `data.item`, `data.recipe` | `item_definition`, `item_recipe` | `item_definition` |

### 7.2 引用规则

- 三个 hero data tools 的 `hero_id` 必须引用当前计划中前序 `resolve_hero` 的
  `data.hero.hero_id`。
- `dota.item_info.item_id` 必须引用当前计划中前序 `resolve_item` 的
  `data.item.item_id`。
- Controller 不得直接写已知数值 ID，也不得复用历史实体 ID。
- `dota.item_info` 在物品无配方时可以不产出 `item_recipe`；只有用户询问配方且计划将
  `item_recipe` 列入 required evidence 时才形成相应义务。

### 7.3 Source metadata

ToolResult source 统一公开：

```json
{
  "name": "Valve Dota 2 Datafeed snapshot",
  "kind": "official_snapshot",
  "url": "https://www.dota2.com/datafeed",
  "status": "committed_snapshot"
}
```

快照 patch、generated_at 和 schema version 放在 ToolResult metadata 和 evidence value 中，
不把本地绝对路径暴露给客户端。

## 8. Controller、Answer 与 Critic

### 8.1 Controller

Tool catalog renderer 自动公开 schema 和引用合同；Controller Prompt 的 Supported 段补充：

- 英雄当前静态属性；
- 英雄技能、先天技能、神杖和魔晶说明；
- 英雄 10/15/20/25 级天赋树；
- 物品定义、价格、主动/被动效果、配方和中立等级。

同时明确：

- “是什么/多少/怎么合成”属于静态目录查询；
- “哪个好/胜率最高/热门/推荐出什么”需要统计工具；
- 缺少统计能力时返回 `capability_boundary`，不能用静态描述伪装推荐结论。

### 8.2 计划示例

```text
“莉娜有哪些技能？”
  resolve_hero
  -> dota.hero_abilities
  -> dota.hero_talent_tree
  -> natural_language_answer

“莉娜的龙破斩是什么技能？”
  resolve_hero
  -> dota.hero_abilities
  -> natural_language_answer

“莉娜的属性和天赋树”
  resolve_hero
  -> dota.hero_attributes
  -> dota.hero_talent_tree
  -> natural_language_answer

“黑皇杖多少钱，怎么合成？”
  resolve_item
  -> dota.item_info
  -> natural_language_answer
```

### 8.3 Answer

V3.3-3 继续使用 `natural_language_answer`，不新增结构化前端卡片 contract。自然回答规则增加：

- 只使用 Catalog evidence 中已经规范化的文本和数值；
- 区分基础值、每级成长值和技能等级数组；
- 天赋按 10/15/20/25 级 left/right 展示；
- 明确区分普通技能、先天技能、Scepter 和 Shard 效果；
- 物品回答区分本体、图纸、组件和升级目标；
- 合成物品用“组件（中文名（English））｜价格｜属性”表格展示组件和独立图纸行，并用
  cost breakdown 校验总价；只有不一致时才用自然语言说明差异，不暴露内部字段名。
- 披露目录 patch 和同步时间；
- 不根据静态字段推断出装强度、技能加点优先级或天赋胜率。
- 用户可见回答不得暴露 `has_shard`、`is_innate`、`special_bonus_*`、
  `talent_internal_name` 等内部 schema/token 名；只使用“魔晶升级”“先天技能”等自然标签。
- 完整英雄技能查询按 Catalog 顺序展示技能，并在末尾附带 10/15/20/25 级左右天赋表；
  不增加重复的技能分类汇总或“相关天赋”章节。
- 单技能查询只输出命中的技能；除非用户同时询问天赋，否则不附其他技能或完整天赋树。

### 8.4 Critic 边界

现有 rule-first Critic 继续检查 evidence completeness、Tool failure、Answer status 和
confidence。本阶段不新增第二个 LLM reviewer，也不实现逐句 claim/evidence 对齐；精确性主要由
规范化结构、mandatory evidence、回答规则和回归测试保证。结构化 `game_reference` contract
留作后续能力，不是 V3.3-3 完成条件。

## 9. 实施顺序

严格按以下顺序实施。每个工作项完成后更新同日中英文 progress；不得提前把后续阶段写成完成。

### A：数据源与快照合同

#### A1 — 设计合同冻结

- 新增本文档。
- 冻结数据源、快照 schema、工具名称、evidence kinds、非目标和验收顺序。
- 只修改文档，不修改运行时代码。

#### A2 — Valve Datafeed transport

- 将 Datafeed 获取逻辑收敛为可测试的离线 transport。
- 支持 english/schinese 的 hero、ability、item 和 patch manifest 请求。
- 保持固定官方 host、超时和有限 retry；不接受调用者提供任意 URL。

#### A3 — 规范化领域模型

- 实现 manifest、hero、ability、talent tier、item 和 recipe 模型。
- 实现双语合并、HTML 清理、数值占位符和 talent bonus join。
- 对悬空 ID、未解析 token、非法天赋层和 recipe 图错误 fail-fast。

#### A4 — 快照生成

- 扩展 `sync_game_data.py`，一次生成 manifest、三个 catalog 文件和开发者同步审计文件。
- 先完整生成到临时目录并校验，再替换目标文件。
- 生成后审查结构和 diff；不在请求路径自动更新。

#### A5 — 同步与快照测试

- fixture 覆盖双语合并、普通 special value、talent bonus、Scepter/Shard、物品描述和配方。
- 快照合同测试不固定英雄/物品总数或具体当前数值。
- 验证 committed snapshot 可由当前 schema 完整加载。

### B：Runtime Catalog 与解析器

#### B1 — DotaCatalogRepository

- 实现启动时加载、ID 查询和 hero/ability/talent/item 关系查询。
- manifest 和数据文件不一致时启动失败。

#### B2 — `resolve_hero` 归位

- 将工具注册从 STRATZ 模块迁入 catalog 模块。
- 保持工具名和输出引用合同不变。
- 删除旧重复注册和 handler，不保留并行路径。

#### B3 — `resolve_item`

- 增加中文、英文、内部名和人工 alias 解析。
- 固定 resolved/ambiguous/not_found 结果和候选上限。
- 图纸和最终物品采用明确优先级。

#### B4 — Catalog 回归

- 验证 resolver、只读加载、并发查询和错误边界。
- 确认现有 STRATZ/OpenDota 工具仍可引用原 `resolve_hero` 输出。

### C：查询工具与 EvidenceGraph

#### C1 — `dota.hero_attributes`

- 注册 input/output/ref/source/evidence 合同。
- 输出英雄身份、属性、战斗字段和快照元数据。

#### C2 — `dota.hero_abilities`

- 输出有序技能、先天/Scepter/Shard 标记、等级数值和规范化描述。
- 不混入天赋技能。

#### C3 — `dota.hero_talent_tree`

- 输出四层左右分支和已解析显示文本。
- talent evidence 必须关联 hero 和 talent ability ID。

#### C4 — `dota.item_info`

- 输出物品定义、属性、主动/被动效果和可选 recipe graph；配方边包含图纸、组件、升级目标
  的必要展示定义和可审计成本明细。
- 无配方物品不伪造空配方证据。

#### C5 — Evidence 与 registry 收口

- 为六个工具补全 evidence extractor、mandatory evidence 和 output paths。
- 验证 Controller catalog、plan validation、reference execution 和 evidence producibility。

### D：Controller 与自然回答

#### D1 — Controller capability 描述

- 更新 Supported/Unsupported 边界和 tool planning examples。
- 固定静态事实与统计推荐的分界。

#### D2 — Answer 静态目录规则

- 增加属性、技能等级、天赋树、Scepter/Shard、物品配方和快照披露规则。
- 流式 Answer 行为保持不变。

#### D3 — Graph 端到端回归

- 覆盖英雄属性、技能、天赋、组合查询、物品定义和配方查询。
- 覆盖 resolver ambiguity、引用错误、缺 evidence 和 LLM error。
- 确认所有成功路径仍经过 Tool -> Evidence -> Answer -> Critic。

### E：验收与文档收口

#### E1 — 真实同步验收

- 使用 Valve 当前 Datafeed 生成完整双语快照。
- 检查未解析 token、悬空引用、天赋树、配方图和 manifest 一致性。
- 人工抽查至少一个英雄的属性/普通技能/先天技能/天赋，以及一个主动物品和一个合成物品。

#### E2 — 完整质量门禁

- API focused tests、全量 pytest、Ruff 和 `git diff --check` 通过。
- 如前端无代码变化，不新增无关前端测试声明。
- `/debug/plan` 和真实 Chat Run 各完成一次静态目录查询冒烟。

#### E3 — 架构与使用文档

- 更新 architecture、API/README、数据同步命令和快照审查说明。
- 中英文 progress 对齐实际完成项、测试结果和未实现边界。
- 将本文状态更新为 V3.3-3 已完成。

## 10. 预计文件变化

主要新增或修改：

```text
apps/api/scripts/sync_game_data.py
apps/api/app/data/catalog/*
apps/api/app/integrations/valve/*
apps/api/app/agentic/tools/dota_catalog_tools.py
apps/api/app/agentic/tools/hero_tools.py
apps/api/app/agentic/tools/registry.py
apps/api/app/agentic/evidence/extractors.py
apps/api/app/agentic/prompts/controller.py
apps/api/app/agentic/answer/synthesizer.py
apps/api/tests/test_dota_catalog_sync.py
apps/api/tests/test_dota_catalog_tools.py
apps/api/tests/test_agentic_graph.py
docs/technical/architecture.md
apps/api/README.md
```

具体文件可在实现时按当前模块职责微调，但不得绕过 integration/transport、ToolRegistry、
EvidenceGraph 或 committed snapshot 边界。

## 11. 测试矩阵

### 11.1 数据层

- 双语 ID join 和内部名一致性。
- hero/ability/item ID 唯一。
- 英雄 ability/talent 引用闭合。
- talent bonus 占位符完整替换。
- HTML/entity/换行规范化。
- recipe graph 无悬空边和循环。
- manifest patch/schema/count 与内容一致。

### 11.2 Tool 层

- 英雄和物品的中英文 exact/fuzzy/ambiguous/not_found。
- 所有下游 ID 参数必须使用合法 plan-local reference。
- ToolResult source 和 metadata 不泄漏本地路径。
- selected tool call 的 mandatory evidence 按 call ID 满足。
- 快照缺失/损坏直接暴露稳定启动或执行错误，不访问网络 fallback。

### 11.3 Graph 层

1. “莉娜基础属性”只执行 resolver + attributes。
2. “莉娜技能和天赋”复用一次 resolver，执行 abilities + talent tree。
3. “黑皇杖效果和配方”执行 item resolver + item info。
4. “莉娜最强天赋”在没有统计工具时不把静态天赋列表伪装成强度结论。
5. missing evidence 继续按 V3.2 规则最多 replan 一次。
6. Answer/Tool/validation 错误保持现有终态优先级。
7. Stateful Chat Run 持久化公开响应、完整 assistant message 和 compact Turn 审计记录，
   不持久化完整 catalog payload。

## 12. 完成定义

V3.3-3 完成必须同时满足：

- Valve Datafeed 能通过离线命令生成完整、双语、版本化且运行时目录无未解析展示 token 的快照；
  已审核排除实体的原始 token 只允许存在于开发者同步审计文件。
- 运行时静态查询不访问任何上游网络。
- `resolve_hero` 只有一个注册位置且现有 STRATZ/OpenDota 引用兼容。
- `resolve_item` 和四个目录查询工具具有完整 input/ref/output/evidence/source 合同。
- 英雄属性、技能、天赋树、物品定义和配方可以通过统一 Agent Graph 回答。
- 静态事实和统计推荐边界在 Prompt、测试和文档中一致。
- 不存在 intent 专用执行分支、第三方静态 fallback、mock 数据或旧/新并行目录路径。
- 真实同步、focused tests、全量回归、lint、diff check 和文档收口全部通过。

## 13. 后续阶段候选

以下能力不阻塞 V3.3-3：

- 从 Dota 2 客户端 VPK 生成或交叉校验目录；
- 本地缓存的官方英雄、技能和物品图片；
- 结构化 `game_reference` 回答 contract 和前端卡片；
- STRATZ/OpenDota 出装率、技能加点率、天赋选择率和胜率工具；
- 静态目录与版本改动记录的跨版本 diff 查询。
