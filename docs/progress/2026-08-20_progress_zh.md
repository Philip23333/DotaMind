# 2026-08-20 进度快照

## 15:05 — Chat 空白页与全高内容区域

### 已完成

- 顶部的 `DotaMind` 与 “Dota 2 智能分析助手”文案已移除；桌面端主区域不再保留顶部 header，聊天内容可使用完整高度。
- 左侧栏恢复带图标的“聊天记录”标题；移动端打开侧栏按钮与运行错误提示改为主区域悬浮元素，不占用内容高度。
- 每次进入聊天页都从新的空白 thread 开始，不再恢复 localStorage 中上次选中的 session。
- 空白新聊天页将原有 `DM` 字母块改为真实 `simple-icons` Dota 2 SVG 图标，红色图块固定为 150 × 150 px。

### 验证

- `apps/chat`：变更文件的 `npx eslint` 通过；`npm test` 为 10 passed（5 files）；`npx tsc --noEmit` 通过；`npm run build` 通过。
- 本地浏览器确认顶部 header 数量为 0、“聊天记录”标题为 1，空白页 Dota 图标实际尺寸为 150 × 150 px，且没有 “Dota 2 智能分析助手”文案。

### 已知边界

- 启动覆盖层仍保留其独立的 `DotaMind` 标题；本次移除的是进入聊天后的主区域顶部标题。
- 已存储的历史聊天、置顶状态和 transcript 未删除，仍可从左侧列表手动打开。

## 13:58 — 底部备案信息

### 已完成

- 聊天页底部仅保留备案号“鄂ICP备2026044062号-1”，并链接至工信部备案查询站；已移除原有的免责提示文案。

### 验证

- 用户明确指定此极小视觉调整不运行测试或构建。

## 14:12 — 常驻回答复制按钮

### 已完成

- AI 回答的复制按钮移出消息文档流，绝对定位在回答下方的既有消息间距内；不会再因为鼠标悬停出现或消失而推挤回答内容。
- 已移除 `autohide` 行为，完成的 AI 回答默认显示复制按钮；仍在生成的回答继续隐藏复制操作。

### 验证

- `apps/chat`：`npx tsc --noEmit` 通过。

## 15:10 — 系列赛全对局详情与跨源 Valve ID 链路

### 已完成

- `pandascore.resolve_match_games` 在未指定局号时返回唯一系列赛中 PandaScore Fixture 实际提供的全部对局；指定局号时仍只返回该局，不创建未出现的对局。
- `dota.resolve_valve_matches` 批量消费 PandaScore competition/game context，按局执行严格的 OpenDota 联赛、战队、时间、时长、局序和胜者匹配，输出 Valve Match ID 列表与逐局映射证据。
- `opendota.match_details` 合并赛果、十人面板、解析覆盖和 BP 查询，只接受 Valve Match ID 列表；PandaScore Series/Match/Game ID 不再声明为可直接引用的下游路径。
- Controller Prompt 和 Tool Catalog 明确 `PandaScore → Valve Match ID → OpenDota` 调用链；真实 `ambiguous_*` / `not_found` / `insufficient_signals` 状态继续保留，不加入 Checkpoint、重试、最近匹配或其他数据源兜底。
- 运行时 `max_tool_calls_total` 从 8 提升至 16；批量工具将最多五局的完整详情收敛到固定工具链中。

### 验证

- API 定向集合：90 passed；API 全量：613 passed、21 skipped、1 warning。
- `uv run --project apps/api ruff check apps/api/app apps/api/tests` 通过；`git diff --check` 通过。
- `apps/chat`：`npm test` 10 passed；`npm run lint` 通过；`npm run build` 通过。

### 已知边界

- 联赛、战队或比赛跨源解析仍保持显式歧义；Checkpoint 用户澄清未在本阶段接入。
- OpenDota 详情批量工具最多接受五个 Valve Match ID；上游缺失 BP 或解析数据时只报告实际覆盖，不伪造 evidence。

## 14:15 — 最新回答底部留白

### 已完成

- 消息列表的末尾内边距增加一行空间，确保最新 AI 回答的复制按钮下方与固定输入框之间保留稳定留白。

### 验证

- 仅调整 Tailwind 间距 class；未运行测试或构建。

## 14:21 — TI 快捷提问

### 已完成

- 输入框获得焦点时，会在输入框上方显示“本届TI最新战况”快捷提问按钮；失去输入焦点或回答生成中时隐藏。
- 点击按钮会通过现有 composer 写入并直接发送“本届TI最新战况”；按钮的按下事件保留输入焦点，避免在点击前收起入口。

### 验证

- `apps/chat`：`npx tsc --noEmit` 通过。
- 本地浏览器确认聚焦“消息输入框”后，快捷按钮可见且唯一；未发送真实查询。

### 已知边界

- 当前只提供进行中 TI 的单一快捷问题；未引入根据赛事日历或外部状态动态生成快捷问题的逻辑。

## 14:23 — 快捷提问限于新对话

### 已完成

- “本届TI最新战况”入口仅在消息为空的新对话中随输入框焦点显示；已有聊天不会显示。
- 新对话发送第一条消息后，入口会随消息列表变为非空而自动消失。

### 验证

- `apps/chat`：`npx tsc --noEmit` 通过。

## 16:42 — coverage 序列化与跨源引用 Prompt 修复

### 已完成

- `pandascore.resolve_match_games` 将 `ResolvedMatchGames.coverage` 按列表逐项序列化；有数据返回字典列表，无数据返回 `[]`，移除旧的单对象/`None`路径。
- 新增处理器级异步回归测试，覆盖两局 coverage、空 coverage、两局 games、两条 `resolution_inputs` 与 transport `aclose()`。
- Controller Prompt 补充 `competition`、`games`、`valve_matches`、`details` 四个示例调用 ID 的精确跨源引用映射，并明确这些引用已由 Tool Catalog 声明兼容；保留不猜测、无最近候选、无 fallback 规则。
- `controller.base` 从 `v4` 升至 `v5`，并重新生成 UTF-8/LF golden fixture；未修改 Validator、ToolDefinition、Graph、重试预算、Checkpoint 或 ambiguous 行为。

### 验证

- coverage 定向集合：20 passed。
- Prompt/Controller 定向集合：59 passed。
- API 全量：616 passed、21 skipped、1 warning。
- `uv run --project apps/api ruff check apps/api/app apps/api/tests` 通过；`git diff --check` 通过。

### 已知边界

- 使用真实 `AgentController` 和固定链路计划对三种 IW/TS 查询做规划校验时，三者均触发既有 `dota.resolve_valve_matches.competition` 空字典占位校验错误；本次按范围未修改 Validator 或工具契约，也未进行真实上游请求。
- IW vs TS 的 Valve Match ID 映射失败仍不属于本次修复范围。
