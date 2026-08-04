# DotaMind Chat

基于 Next.js 与 assistant-ui 的最小聊天前端。它不运行模型，也不复制
DotaMind 的 Agent Runtime；浏览器只调用 `POST /api/v1/plan/stream`。

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
`session_id`。前端使用 POST `fetch` 读取 `application/x-ndjson`，跨网络 chunk 累计后端
真实的 LLM token；它不会为直接回答或结构化回答伪造打字机效果。运行卡展示分析、工具、
回答和核验阶段，成功自动折叠，失败或取消保持展开；最终结果会替换核验前的临时正文。

生产代理必须为 `/api/v1/plan/stream` 关闭响应缓冲（API 已设置
`X-Accel-Buffering: no` 和 `Cache-Control: no-cache, no-transform`），否则 token 会被代理
攒到请求结束才送达浏览器。页面刷新后聊天记录不会恢复；断线重连、心跳、会话列表、附件
和用户认证均不属于这个最小阶段。
