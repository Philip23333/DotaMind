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

当前版本在首次打开页面时生成并保存一个浏览器 UUID，并通过会话侧栏创建、选择、重命名
和删除多个本地匿名会话，并可将会话置顶。置顶状态保存在 PostgreSQL，选中的 `session_id` 也保存在 localStorage；切换会话会从
PostgreSQL transcript 恢复消息。前端使用 POST `fetch` 读取 `application/x-ndjson`，跨
网络 chunk 累计后端真实的 LLM token；它不会为直接回答或结构化回答伪造打字机效果。运行
卡展示分析、工具、回答和核验阶段，成功自动折叠，失败或取消保持展开；最终结果会替换
核验前的临时正文，并同步服务端返回的最新会话标题和排序。移动端使用抽屉式聊天列表，
聊天管理操作通过“更多”菜单提供，不依赖 hover。

生产代理必须为 `/api/v1/plan/stream` 关闭响应缓冲（API 已设置
`X-Accel-Buffering: no` 和 `Cache-Control: no-cache, no-transform`），否则 token 会被代理
攒到请求结束才送达浏览器。断线重连、心跳、附件、跨设备同步和用户认证均不属于这个
阶段。
