# DotaMind Chat

基于 Next.js 与 assistant-ui 的多聊天前端。它不运行模型，也不复制
DotaMind 的 Agent Runtime；正式聊天通过 Chat Run API 创建、订阅和取消后台 Run。

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
```

当前版本在首次打开页面时生成并保存一个浏览器 UUID，并由 assistant-ui
`RemoteThreadListRuntime` 将一个 thread 映射到一个 DotaMind `session_id`。新聊天先使用
assistant-ui optimistic thread，首次发送时才调用后端创建 session；重命名、删除和置顶仍由
DotaMind Session API 完成。置顶状态和 transcript 保存在 PostgreSQL，选中的 `session_id`
保存在 localStorage。每个已启动 thread 保持独立 `LocalRuntime`，发送时先调用
`POST /api/v1/chat/sessions/{session_id}/runs`，再从
`GET /api/v1/chat/runs/{run_id}/events?after=0` 读取可重放 NDJSON。

`ThreadHistoryAdapter` 从 PostgreSQL transcript 加载历史；存在活动 Run 时以
`unstable_resume` 重放 Redis 事件并恢复回答。切换、刷新或订阅 Abort 不会取消后台 Run，
只有显式点击“停止生成”才调用指定 Run 的 cancel API。运行阶段、工具信息和 Run ID 保存在
assistant message metadata，不再维护独立的浏览器级 Run Store。移动端使用抽屉式聊天列表，
聊天管理操作通过“更多”菜单提供，不依赖 hover。

`/api/v1/plan` 与 `/api/v1/plan/stream` 只保留 `/debug/plan` 的 stateless 调试用途；生产
聊天不再调用它们。Chat Run 事件包含 Redis Stream 的重放 cursor 和 heartbeat，最终 Turn
由 PostgreSQL 原子提交。附件、跨设备同步和用户认证均不属于这个阶段。

## 测试

```bash
npm run test
npm run lint
npm run build
```

前端回归覆盖迁移契约、session/thread 映射、稳定 pending message id，以及“订阅断开不取消、
显式停止才取消”的行为边界。
