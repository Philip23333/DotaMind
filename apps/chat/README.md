# DotaMind Chat

基于 Next.js 与 assistant-ui 的多聊天前端。它不运行模型，也不复制
DotaMind 的 Agent Runtime；正式聊天通过 Chat Run API 创建、订阅和取消后台 Run。

## 启动动效

首次渲染会在聊天 UI 上方显示约 1.4 秒的 DotaMind 启动覆盖层。它使用
`simple-icons` 的 Dota 2 单色矢量路径，文字仅显示 “DotaMind”；动画不触发 Chat Run 或 API 请求。用户可按 `Esc` 立即关闭，
`prefers-reduced-motion` 用户只会看到瞬时过渡。

## 视觉主题

聊天界面使用浅灰侧栏与浅灰白主消息区的分层表面；桌面端主区域没有顶部栏，全部高度用于聊天内容。选中、主操作与焦点使用灰度，Dota 红仅保留在启动页图标/进度线、150 px 新聊天图标和低对比度的中央 Dota 2 矢量水印。

仅在消息为空的新对话中，输入框获得焦点时会在其上方显示“本届TI最新战况”快捷提问；点击后直接发送该问题，已有聊天和运行中的回答不显示该入口。

## 本地启动

先启动仓库中的 FastAPI 服务（默认 `http://localhost:8001`），然后：

```bash
cd apps/chat
npm install
npm run dev
```

访问 `http://localhost:3000`。

如需修改 API 地址，复制 `.env.local.example` 为 `.env.local` 并设置：

```text
NEXT_PUBLIC_DOTAMIND_API_URL=http://localhost:8001
NEXT_PUBLIC_DOTAMIND_TEST_OBSERVER_ENABLED=false
```

测试时可同时设置 API 的 `DOTAMIND_TEST_OBSERVER_ENABLED=true` 和前端的
`NEXT_PUBLIC_DOTAMIND_TEST_OBSERVER_ENABLED=true`。聊天主区域右侧会出现测试观测器入口，
抽屉按模型 Prompt、工具输入/输出和模型输出展示当前页面订阅到的完整结构化 Run 事件。
每条记录以可独立折叠的 JSON 卡片展示，Prompt、工具输入、工具输出和模型输出数据块均可一键复制格式化 JSON。
该功能默认关闭，调试载荷不写入 PostgreSQL transcript；刷新后不保证恢复已结束 Run 的观测数据。

当前版本在首次打开页面时生成并保存一个浏览器 UUID，并由 assistant-ui
`RemoteThreadListRuntime` 将一个 thread 映射到一个 DotaMind `session_id`。每次重新进入聊天页都会从新的空白聊天开始，不恢复上次选中的 session；新聊天先使用
assistant-ui optimistic thread，首次发送时才调用后端创建 session；重命名、删除和置顶仍由
DotaMind Session API 完成。置顶状态和 transcript 保存在 PostgreSQL。每个已启动 thread 保持独立 `LocalRuntime`，发送时先调用
`POST /api/v1/chat/sessions/{session_id}/runs`，再从
`GET /api/v1/chat/runs/{run_id}/events?after=0` 读取可重放 NDJSON。

`ThreadHistoryAdapter` 从 PostgreSQL transcript 加载历史；存在活动 Run 时以
`unstable_resume` 重放 Redis 事件并恢复回答。切换、刷新或订阅 Abort 不会取消后台 Run，
只有显式点击“停止生成”才调用指定 Run 的 cancel API。运行阶段、工具信息和 Run ID 保存在
assistant message metadata，不再维护独立的浏览器级 Run Store。移动端使用抽屉式聊天列表，
聊天管理操作通过“更多”菜单提供，不依赖 hover。

当 ChatRun 发布 `checkpoint` 并进入 `waiting_input` 时，assistant message 会显示
`CheckpointCard`。卡片只提交服务端提供的 `checkpoint_type` 与 `option_id`；选择成功后在同一
`run_id` 上调用 resume，并从保存的事件 sequence 继续订阅。刷新页面沿用活动 Run 的 replay
恢复卡片；等待选择期间不会自动取消或猜测候选。

`/api/v1/plan` 与 `/api/v1/plan/stream` 只保留 `/debug/plan` 的 stateless 调试用途；生产
聊天不再调用它们。Chat Run 事件包含 Redis Stream 的重放 cursor 和 heartbeat，最终 Turn
由 PostgreSQL 原子提交。附件、跨设备同步和用户认证均不属于这个阶段。

英雄、普通技能、物品以及 OpenDota/PandaScore 比赛结构化实体中的本地 `image_path` 会由 Chat 转换为当前
API 地址，并按 Markdown 上下文以内联缩略图显示：单实体一级标题为 56×56，普通列表与
叙述为 32×32。比赛详情的横向 BP 表、`选手 / 英雄`列和主装备使用 32×32；装备列中带有
`背包：`、`中立：`或`强化：`标签的物品使用 20×20。横向 BP 仅显示图标且窄屏可横向滚动。
技能加点箭头序列使用技能 `md` 图标，天赋和全属性加点保持纯文本；赛果、对阵和 BP
中的本地战队 Logo 按普通段落 `md`、表格 `sm` 展示。图片由 API 本地静态资源提供，
只接受 `/api/v1/assets/dota/...` 与 `/api/v1/assets/esports/teams/...`，不允许 PandaScore
CDN URL 到达 Chat Response、数据库紧凑响应或浏览器。图片只由结构化路径驱动，不由模型生成 URL。

## 测试

```bash
npm run test
npm run lint
npm run build
```

前端回归覆盖迁移契约、session/thread 映射、稳定 pending message id，以及“订阅断开不取消、
显式停止才取消”的行为边界。

Runtime 卡片会显示 PandaScore/OpenDota 工具的中文名称。失败调用依据公共 runtime
的 `handler_entered`、`dispatch_stage` 和稳定 `failure_code` 区分“未执行”和“执行后失败”，
并使用安全的中文原因，不展示原始异常、完整引用路径或认证信息。
