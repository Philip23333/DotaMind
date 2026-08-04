# DotaMind Chat

基于 Next.js 与 assistant-ui 的最小聊天前端。它不运行模型，也不复制
DotaMind 的 Agent Runtime；浏览器只调用现有的 `POST /api/v1/plan`。

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

当前版本在每次打开页面时创建一个新的会话 UUID，同一页面内的后续消息会复用该
`session_id`。页面刷新后聊天记录不会恢复；服务端流式响应、会话列表、附件与用户认证
均不属于这个最小阶段。
