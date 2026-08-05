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

当前版本在首次打开页面时生成并保存一个浏览器 UUID，并通过会话侧栏创建、选择、重命名
和删除多个本地匿名会话，并可将会话置顶。置顶状态和 transcript 保存在 PostgreSQL，
选中的 `session_id` 也保存在 localStorage。发送时先调用
`POST /api/v1/chat/sessions/{session_id}/runs`，再从
`GET /api/v1/chat/runs/{run_id}/events?after=0` 读取可重放 NDJSON；刷新或切换会话不会
取消后台 Run。Run Store 以 `run_id` 为身份，校验 sequence/session，支持并行 Run、恢复、
Stop/cancel 和后台未读计数。运行卡展示分析、工具、回答和核验阶段，最终结果同步服务端
标题和排序。移动端使用抽屉式聊天列表，聊天管理操作通过“更多”菜单提供，不依赖 hover。

`/api/v1/plan` 与 `/api/v1/plan/stream` 只保留 `/debug/plan` 的 stateless 调试用途；生产
聊天不再调用它们。Chat Run 事件包含 Redis Stream 的重放 cursor 和 heartbeat，最终 Turn
由 PostgreSQL 原子提交。附件、跨设备同步和用户认证均不属于这个阶段。

## 测试

```bash
npm run test
npm run lint
npm run build
```
