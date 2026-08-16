# 2026-08-16 进度快照

## 12:30 — P2.2 赛事届次解析、运行时失败状态与 Chat UI

### 已完成

- `pandascore.resolve_competition` 增加可选 `year`，兼容从 query 中解析四位年份，并在参数年份冲突时返回受控 validation error。
- 赛事候选按 series/full label、parent league、label substring 采用 3/2/1 匹配等级；缺省年份时按进行中、最近历史、最近未来的时间语义选择，不依赖 API 数组顺序、当前年份或固定赛事 ID。
- 成功解析结果增加 `selection` 元数据；`competition_identity` 仍是唯一 mandatory evidence，ambiguous/not_found 不产生身份 evidence。
- 公共 runtime 工具状态增加 `handler_entered`、`dispatch_stage` 和安全映射后的 `failure_code`；实时工具事件同步带有执行阶段信息，raw exception、内部引用和上游正文仍不公开。
- Chat UI 增加 PandaScore/OpenDota 中文工具名、友好失败文案和“未执行”展示；持久化响应与实时事件使用同一稳定错误映射。
- 未新增 intent 路由、固定 TI ID、当前年份硬编码、API endpoint 或 fallback。Controller 增加的是跨赛事通用的范围澄清与年份保留规则，并同步动态目录 golden；未加入固定问句路由。

### 验证

- `uv run --project apps/api pytest apps/api/tests -q`：610 passed，21 skipped，1 warning。
- `uv run --project apps/api ruff check apps/api/app apps/api/tests`：通过。
- `apps/chat`：`npm test` 10 passed；`npm run lint` 通过；`npm run build` 通过。

### 已知边界

- 当前 Controller prompt 仍遵循动态 ToolRegistry 目录与已有通用澄清语义；未按 intent 增加赛事固定 pipeline。
- PandaScore 免费 Fixture 的 Valve ID 缺口和第二阶段跨源推断边界不变；本阶段只改赛事届次选择和公开错误展示。

## 14:05 — Chat 启动动效与像素猫吉祥物

### 已完成

- `apps/chat` 新增全屏 `StartupOverlay`：以 `simple-icons` 的 Dota 2 单色 SVG path 作为红色主图案，叠加项目内的暹罗猫像素精灵，而不是使用生成图中的近似标志。
- 启动层位于既有 Chat Runtime 之外；约 1.4 秒后淡出，不调用 Chat Run、后端 API 或改变会话/线程状态。
- 提供“跳过动画”和 `Esc` 退出；`prefers-reduced-motion` 只执行瞬时过渡。

### 验证

- `apps/chat`：`npm run lint` 通过；`npm test` 10 passed；`npm run build` 通过。
- 本地浏览器验证启动覆盖层的 SVG、像素精灵、自动淡出与“跳过动画”交互；控制台无 error。
- `design-qa.md`：启动态的源图/实现并排视觉审查通过；已清理像素精灵的洋红抠图边缘。

### 已知边界

- 当前动效每次完整页面加载都会展示；未增加持久化的“仅首次访问”标记。
- 未改动 Chat Run API、服务端运行时或现有聊天功能。

## 13:42 — P2.2.1 修复赛事默认届次与历史年份查询

### 已完成

- Controller 规则明确：已命名周期性赛事缺少年份不需要澄清，调用 resolver 时省略 `year`；显式年份必须保留；真正缺少赛事/战队/选手主体时仍返回 clarification。
- `pandascore.resolve_competition` 描述同步声明缺少年份时选择最新届，且不允许仅因年份缺失追问。
- `PandaScoreCompetitions.list_series(year=...)` 在明确年份时发送 `filter[year]`，缺省年份不发送；resolver 先按年份建立 eligible rows，再进行名称匹配和主赛事/资格赛消歧。
- 保留无年份的 active → latest historical → nearest future 语义，显式年份不存在时返回 `not_found`，不回退到其他年份。

### 实时联调

- 独立 8002 API 矩阵：`现在TI的最新战况如何？` 与 `The International 最新战况如何？` 均生成 `tool_plan` 且省略 `year`；`TI 2025 最新战况如何？` 生成 `year=2025`；`现在最新战况如何？` 返回 clarification。
- 真实执行确认：无年份选择 Series `10828` / year `2026`；显式 2025 选择 Series `9555` / year `2025`，后续 `pandascore.list_matches` `handler_entered=true`；独立 API 已停止，8001 未修改。

### 边界

- 未增加 Controller 决策校验器、intent 路由、历史 fallback、固定年份或 Series ID；Runtime 与前端错误展示保持不变。

### 最终验证

- `apps/api/.venv/Scripts/python.exe -m pytest -q`：612 passed，21 skipped，1 warning。
- `apps/api/.venv/Scripts/python.exe -m ruff check app tests`：通过。
- `apps/chat`：`npm test -- --run` 为 10 passed（5 files）；`npm run lint` 通过；`npm run build` 通过。

## 14:07 — 移除启动猫咪吉祥物

### 已完成

- 启动覆盖层移除暹罗猫像素精灵、背景残影及对应本地素材；红色方块中的 `simple-icons` Dota 2 单色 SVG 保留为唯一主图标。
- 启动时长、淡出、“跳过动画”、`Esc` 和减少动态效果行为保持不变；未修改 Chat Run、后端 API 或会话状态。

### 验证

- `apps/chat`：`npm run lint` 通过；`npm test` 10 passed；`npm run build` 通过。
- 本地浏览器在启动中状态确认猫咪图层为 0、Dota 2 SVG 方块存在；“跳过动画”后覆盖层为 0，控制台无 error。
- `design-qa.md` 更新为最终的纯矢量图标视觉验收记录。

### 已知边界

- 当前动效每次完整页面加载都会展示；未增加持久化的“仅首次访问”标记。

## 14:14 — 精简启动文字

### 已完成

- 移除图标下方说明与“正在加载战局洞察”状态文字；启动覆盖层内的可见文案仅保留 `DotaMind` 主标题。
- 保留 Dota 2 SVG 方块、进度线、自动淡出、“跳过动画”、`Esc` 和减少动态效果行为；未改动 Chat Run、API 或会话状态。

### 验证

- `apps/chat`：`npm run lint` 通过；`npm test` 10 passed；`npm run build` 通过。
- 本地浏览器确认启动中的覆盖层文本为 `DotaMind`，两处已移除的小字均不存在。
- `design-qa.md` 更新到最终的纯标题启动态截图与并排审查。

## 14:21 — Dota 2 暗红界面主题

### 已完成

- 移除启动覆盖层右上角“跳过动画”按钮；自动淡出与 `Esc` 退出保持可用。
- 将主界面和侧栏的背景、卡片、边框、输入、焦点及主操作 token 统一为深棕/暗红/暖白配色，保留现有布局与聊天行为。

### 验证

- `apps/chat`：`npm run lint` 通过；`npm test` 10 passed；`npm run build` 通过。
- 本地浏览器确认启动结束后没有跳过按钮，聊天区、侧栏、消息气泡与输入框均采用新的暗红主题且文案可读。
- `design-qa.md` 更新为暗红主界面与无跳过按钮的验收记录。

## 14:29 — 细化暗红聊天布局

### 已完成

- 主内容消息区从 `background` 提升为更浅的 `card` 表面，底部输入框进一步使用较亮的 `popover` 表面；暗红主题、暖白文字与既有交互保持不变。
- 左侧聊天记录列表保持滚动能力但隐藏可见滚动条。
- 主标题栏高度调整为 65 px，与侧栏聊天记录上方的标题栏实际高度一致，使两侧内容起点对齐。

### 验证

- `apps/chat`：`npm run lint` 通过；`npm test` 10 passed；`npm run build` 通过。
- 本地浏览器确认主/侧栏标题均为 65 px、侧栏滚动条宽度为 0、启动覆盖层已正常退出且控制台无 error。
- `design-qa.md` 更新为最终的提亮表面、隐藏滚动条与对齐布局验收记录。

## 14:36 — 浅色主区域与 Dota 2 水印

### 已完成

- 主消息区域切换为暖白浅色表面，输入框使用更亮的浅色表面；该区域的前景与静音文字同步切换为深棕，保证对比度。
- 使用 `simple-icons` 的真实 Dota 2 SVG path 在主区域中央加入低不透明度水印；水印高度固定为内容区的 70%，不响应指针事件，也不影响滚动和输入。
- 暗红侧栏与顶部框架、现有消息/运行时行为保持不变。

### 验证

- `apps/chat`：`npm run lint` 通过；`npm test` 10 passed；`npm run build` 通过。
- 本地浏览器确认水印高度与主区域高度之比为 0.70，浅色主区域内文字可读，启动结束后控制台无 error。
- `design-qa.md` 更新为最终的暖白主区域与水印视觉验收记录。

## 14:44 — 灰白界面与 Dota 红强调

### 已完成

- 侧栏、顶部、主区域和输入框改为浅灰/近白的分层表面；保留明度差与柔和阴影，但不增加硬分割线。
- Dota 红仅用于已选聊天、发送按钮、焦点环及低对比度 Dota 2 水印；文字、边框、消息底色和其余界面 token 统一为灰白系。

### 验证

- `apps/chat`：`npm run lint` 通过；`npm test` 10 passed；`npm run build` 通过。
- 本地浏览器确认侧栏与顶部边框宽度均为 0，灰白层级和红色强调符合预期，控制台无 error。
- `design-qa.md` 更新为灰白界面的最终视觉验收记录。

## 14:53 — 灰白控件与红色 Dota 标志

### 已完成

- 选中项、发送按钮、焦点环和其余交互强调统一改回灰度。
- 启动页的 Dota 2 图块/进度线，以及主区域的低对比度 Dota 2 水印恢复原红色；其他灰白分层、无硬分界线和布局保持不变。

### 验证

- `apps/chat`：`npm run lint` 通过；`npm test` 10 passed；`npm run build` 通过。
- 本地浏览器确认启动页图标和水印为红色，发送按钮为深灰，控制台无 error。
- `design-qa.md` 更新为最终的灰白界面与红色 Dota 标志验收记录。
