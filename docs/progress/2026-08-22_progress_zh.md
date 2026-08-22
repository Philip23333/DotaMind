# 2026-08-22 进度快照

## 01:00 — Markdown 比赛详情信息密度增强

### 已完成

- 比赛详情 Answer 模板改为每队一张横向 BP 表：首列为顺序标签，后续七列展示本队的选择与禁用顺序。
- 选手表改为 `选手 / 英雄 | K/D/A | 经济 | 装备 | 技能加点与天赋`；普通比赛详情只显示加点及天赋数量摘要，装备按主栏、背包、中立和强化分组。
- 购买、加点或天赋 evidence 存在时，Answer 获得按需“出装、加点与天赋”章节规则；只有当前问题明确要求时，才展开目标选手的完整购买顺序、加点和实际天赋选择。
- Chat 继续只渲染 Markdown：横向 BP 英雄名确定性替换为中尺寸图标且不显示名称；合并英雄列与主装备使用中尺寸图标，背包、中立物品和强化使用小尺寸图标。
- Markdown 表格增加横向滚动容器；未新增图标尺寸、结构化比赛面板、HTML 折叠、Controller 路由或数据层契约。

### 验证

- Answer 定向测试：18 passed。
- Chat `dotamind-api` 定向测试：11 passed。

### 已知边界

- 纯 Markdown 不提供真实折叠交互；普通比赛详情不自动渲染十名选手的完整购买和加点日志。
- 当前没有离线技能或天赋图标资产，技能加点与天赋详情保持 evidence 支撑的文字和 Markdown 表格。

## 01:05 — Markdown 比赛详情全量验证

### 验证

- API 全量：655 passed、21 skipped、1 warning。
- Answer Prompt 与定向 Ruff 检查通过。
- Chat 全量：8 个测试文件、24 个测试通过。
- Chat ESLint 与 Next.js production build 通过。
- `git diff --check` 通过。

## 01:43 — OpenDota 选手 evidence 字段投影

### 已完成

- 修复 `match_details_evidence()` 的数据重复：记分牌、购买顺序、技能加点和天赋 evidence 不再各自携带完整选手对象。
- 记分牌保留展示字段与购买/加点/天赋计数；三类进度 evidence 只保留对应序列和选手/英雄身份字段。
- 原始 `ToolResult`、EvidenceGraph 双层结构、Answer Prompt、Chat Run 和前端均保持不变。

### 验证

- `tests/test_agentic_opendota_match_tools.py`：9 passed。
- OpenDota evidence 投影回归断言与定向 Ruff 检查通过。
- 使用已落库的真实三局比赛 ToolResult 重跑 extractor：Answer messages 约从 3.10 MB 降至 1.30 MB；原始 ToolResult 未改写。

### 已知边界

- 本次未移除 `EvidenceGraph.tool_results`，因此没有改变原始结果进入 Answer Prompt 的总体模式；只消除了 evidence 内部的字段交叉复制。

## 02:10 — Controller 最小化比赛详情证据规划

### 已完成

- 普通比赛详情的 `required_evidence` 明确限定为实际展示的身份映射、赛果、解析状态、BP 与十人记分牌。
- 购买顺序、技能加点和天赋选择仅在用户明确询问对应历史时才加入证据义务；不因 `opendota.match_details` 能够产出这些字段而默认规划。
- 未改动 Tool Registry 的可产出 evidence 契约、Graph 执行路径或 `intent` 路由语义。

### 验证

- `tests/test_agent_controller.py`：42 passed。
- Controller 规则、OpenDota 工具说明和定向测试 Ruff 检查通过。
- `git diff --check` 通过。

## 02:20 — Answer 专用 Evidence View

### 已完成

- 自然语言 Answer 不再序列化完整 `EvidenceGraph` 或原始 `tool_results`；发送给模型的是 required evidence 对应的 evidence、缺失项与数据质量。
- 未被当前请求要求的购买、技能加点和天赋 evidence 不会激活展示规则，也不会进入 Answer Prompt。
- 原始工具结果仍保留在执行态，供审计、测试观察器和后续确定性处理使用。

### 验证

- `tests/test_agentic_answer.py`：20 passed。
- 新增回归覆盖：原始工具结果及未要求的选手进度 evidence 不进入 Answer；明确要求购买顺序时只投影购买 evidence。
- Answer 定向 Ruff 检查与 `git diff --check` 通过。

## 02:35 — Chat 历史紧凑响应

### 已完成

- Chat Run 在写库和发布 `result` 事件前，将响应投影为状态、原因/错误码、Answer 与 runtime 摘要；不再保存 plan、原始工具结果、EvidenceGraph、review、errors 或 trace。
- 为保持现有 Markdown 英雄/物品图标展示，仅从原始工具结果提取去重后的轻量 `catalog_visual_entities`，不保留原始数据包。
- 会话读取对旧的完整 `public_response` 应用同一投影，无需迁移历史行即可避免刷新重新下载大结果。

### 验证

- API 定向：`tests/test_chat_response.py`、`tests/test_chat_run_executor.py`、`tests/test_chat_routes.py` 共 10 passed、1 warning。
- Chat `src/lib/dotamind-api.test.ts`：12 passed；相关 ESLint 通过。
- API Ruff 与 `git diff --check` 通过。

## 02:50 — P0 全量自动化回归

### 验证

- API 全量：660 passed、21 skipped、1 warning。
- API 全量 Ruff 与 `git diff --check` 通过。
- Chat 全量：8 个测试文件、25 个测试通过。
- Chat ESLint 与 Next.js production build 通过。

### 测试收口

- 同步 Controller system prompt golden fixture 与阶段 1 的规则文本。
- Catalog 完整技能回答测试改为断言 Answer Evidence View 的 JSON 表示；完整技能计划本来已显式要求天赋 evidence，未放宽任何 Answer 投影边界。

## 10:50 — Chat 紧凑响应图标实体重读修复

### 已完成

- `compact_chat_response()` 对已紧凑的响应保留既有 `catalog_visual_entities`；仅旧响应缺失该字段时才从原始 `tool_results` 派生。
- 修复新 Chat Run 写库后在会话读取时二次压缩、丢失 Markdown 英雄/物品图标实体的问题。

### 验证

- 定向覆盖紧凑响应幂等性，以及会话读取保留新格式图标实体。

## 11:05 — 比赛详情图标语义修正

### 已完成

- 修正紧凑 Chat 响应的 Catalog 图标投影：带 `hero_image_path` / `item_image_path` 的记录只采集对应实体专属名称，不再把选手通用 `name` 误写为英雄或物品别名。
- 选手 / 英雄合并列增加前端上下文保护：仅在 ` · ` 后的英雄部分插入英雄图标，即使旧紧凑响应含有错误别名也不会替换选手名。
- 横向 BP 表的英雄图标改用 `lg`；选手装备中保留主装备文字与中尺寸图标，背包、中立和强化只显示小图标，强化图标保留在括号内但移除文字标签。
- 普通比赛详情选手表移除“技能加点与天赋”列；针对明确询问选手加点或天赋的按需详情规则保持不变。

### 验证

- Chat 图标格式化定向测试：13 passed。
- API 紧凑响应与 Answer Prompt 定向测试：2 passed（20 deselected）；涉及文件 Ruff 检查通过。
- API 全量：662 passed、21 skipped、1 warning；Chat 全量：26 passed；ESLint 与 Next.js production build 均通过。

### 已知边界

- 已保存的历史紧凑响应不会被迁移；前端的选手/英雄列保护会避免其中的污染别名替换选手名，新响应会使用修正后的实体投影。

## 11:10 — 选手/英雄合并列图标位置

### 已完成

- 选手 / 英雄合并列仍仅根据分隔符 ` · ` 后的英雄文本判定头像，但将已判定的英雄头像移动到整个单元格最前端，统一显示为“英雄头像 选手 · 英雄（等级）”。

### 验证

- Chat `dotamind-api` 定向测试：13 passed；ESLint 与 `git diff --check` 通过。
