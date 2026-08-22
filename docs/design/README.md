# DotaMind Design Documentation

`docs/design/` 按文档职责分类。版本目标、架构原理、工具专项和能力路线图不得继续
混放在目录根部。

## 阅读顺序

1. 先读最新 [`../progress/`](../progress/) 中英文进度快照。
2. 读 [`../technical/architecture.md`](../technical/architecture.md) 和
   [`architecture/整体架构.md`](./architecture/整体架构.md) 了解当前实现。
3. 读 [`versions/DotaMind_MVP_v2.5.md`](./versions/DotaMind_MVP_v2.5.md)
   了解 constrained tool calling 不变量。
4. 按任务阅读 [`architecture/Controller层.md`](./architecture/Controller层.md)、
   [`architecture/ConversationMemory层.md`](./architecture/ConversationMemory层.md) 或其他分层文档。
5. 只有需要阶段背景与验收历史时，再读 V3.2/V3.3 `versions/` 蓝图。

## `versions/`：版本设计蓝图

定义某个版本或实施阶段的目标、非目标、运行图、状态模型、实施顺序和完成定义。

- [`DotaMind_MVP_v2.5.md`](./versions/DotaMind_MVP_v2.5.md) — constrained
  tool calling 架构底座。
- [`DotaMind_V3.0_design.md`](./versions/DotaMind_V3.0_design.md) — 已实现业务
  能力和产品蓝图。
- [`DotaMind_V3.2_design.md`](./versions/DotaMind_V3.2_design.md) — Agent Runtime
  Foundation 总体蓝图。
- [`DotaMind_V3.2-1_design.md`](./versions/DotaMind_V3.2-1_design.md) —
  Run / Attempt / Budget 阶段实施蓝图。
- [`DotaMind_V3.2-2_design.md`](./versions/DotaMind_V3.2-2_design.md) —
  Prompt Registry 阶段实施蓝图。
- [`DotaMind_V3.2-3_design.md`](./versions/DotaMind_V3.2-3_design.md) —
  有界 missing-evidence Recovery/Replan 阶段实施蓝图。
- [`DotaMind_V3.2-4_design.md`](./versions/DotaMind_V3.2-4_design.md) —
  stateful request idempotency 阶段实施蓝图。
- [`DotaMind_V3.2-5_design.md`](./versions/DotaMind_V3.2-5_design.md) —
  Redis Session Store、分布式 lease 与 fencing 阶段实施蓝图。
- [`DotaMind_V3.3-1_design.md`](./versions/DotaMind_V3.3-1_design.md) —
  PostgreSQL 聊天持久化历史蓝图；当前消息窗口合同以后续覆盖说明为准。
- [`DotaMind_V3.3-2_design.md`](./versions/DotaMind_V3.3-2_design.md) —
  已完成的 detached Chat Run、事件恢复与 assistant-ui 前端蓝图。
- [`DotaMind_V3.3-3_design.md`](./versions/DotaMind_V3.3-3_design.md) —
  已完成的 Valve committed Catalog 与静态查询工具蓝图。
- [`DotaMind_V3.3-4_design.md`](./versions/DotaMind_V3.3-4_design.md) —
  已完成的统一 direct answer、删除历史回忆模式与 basis 合同轻量收敛蓝图。
- [`DotaMind_V3.4-UX_assets_design.md`](./versions/DotaMind_V3.4-UX_assets_design.md) —
  当前 v3.4 用户体验的 Valve 技能与 PandaScore 战队本地图标资产边界。

版本蓝图负责回答“这个版本要到哪里”，但当前实现状态仍以最新进度快照和工作树为准。

## `architecture/`：架构设计思路与运行时清单

解释系统分层职责、数据流、校验边界、失败语义和当前/目标节点关系。

- [`整体架构.md`](./architecture/整体架构.md) — 当前端到端架构、Graph、
  Evidence、Session、Runtime 与 V3.2 后续边界的统一入口。
- [`Controller层.md`](./architecture/Controller层.md)
- [`Validator层.md`](./architecture/Validator层.md)
- [`Tool层.md`](./architecture/Tool层.md)
- [`Evidence层.md`](./architecture/Evidence层.md)
- [`Answer+Critic层.md`](./architecture/Answer+Critic层.md)
- [`DotaMind_V3_node_tool_edge_inventory.md`](./architecture/DotaMind_V3_node_tool_edge_inventory.md)

这里的 Tool 层文档描述 Tool Runtime 在整体架构中的职责，不等同于 `tools/` 下的
具体工具专项设计。

## `tools/`：工具专项设计与审计

记录具体数据源、参数语义、时间窗口、证据口径和工具重构决策。

- [`STRATZ工具审计与重构输入.md`](./tools/STRATZ工具审计与重构输入.md)
- [`time_patch_filtering.md`](./tools/time_patch_filtering.md)

STRATZ GraphQL 的实测 operation/schema inventory 仍放在 `docs/technical/`，因为它们
是 provider 技术事实，不是产品设计蓝图。

## `roadmaps/`：能力缺口与优先级输入

记录阶段性的缺口分析、业务工具优先级和未来切片，不作为当前运行时已实现能力声明。

- [`V3.0_功能闭环缺口盘点.md`](./roadmaps/V3.0_功能闭环缺口盘点.md)
- [`agent_basic_tool_priorities.md`](./roadmaps/agent_basic_tool_priorities.md)

这些路线图是能力输入，不是当前实现顺序；实现状态必须对照最新进度与工作树。

## 分类规则

- 新的完整版本或阶段蓝图放入 `versions/`。
- 跨业务能力的分层、状态流、节点、contract、evidence 和失败语义放入
  `architecture/`。
- 单个 provider、工具族、参数或数据口径的设计/审计放入 `tools/`。
- 能力缺口、优先级和候选切片放入 `roadmaps/`。
- 当前 API、配置和 provider schema/reference 事实放入 `docs/technical/`。
- 已被替代且仅保留历史意义的文档放入 `docs/archive/`。

移动文档时必须同步更新当前入口、代码注释和有效交叉链接。历史进度快照保持原始记录，
通过新的当日追加章节说明迁移后的规范路径。

## 当前基线

V3.2-1 至 V3.2-6 均已完成；V3.3-1 至 V3.3-4 的能力也已完成并继续演化。
当前正式多轮合同是 PostgreSQL 完整消息 + Redis `RecentDialogueWindow` + Chat Run，
而不是 V3.2 早期 compact Turn history。阅读历史蓝图时必须先看其
顶部 supersession 说明，再以当前 architecture/technical 文档校正。
