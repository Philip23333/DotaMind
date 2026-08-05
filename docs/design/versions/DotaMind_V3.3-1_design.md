# DotaMind V3.3-1：PostgreSQL 聊天持久化与匿名浏览器多聊天管理

## 目标与边界

本阶段把 PostgreSQL 定义为聊天记录与会话记忆的权威存储，并在不引入用户登录的前提下支持同一浏览器的多个聊天会话。浏览器通过一个本地生成并持久化的 UUID v4 作为匿名身份；后端只保存其 SHA-256，不保存原始浏览器标识。

本阶段不包含账号体系、跨浏览器同步、分享链接、跨设备迁移、全文搜索、附件、消息编辑/分支、断线续传或 LangGraph checkpoint。LangGraph 继续负责单次请求的运行态，PostgreSQL 保存可恢复的聊天业务历史。

## 存储职责

```text
浏览器 localStorage
  browser_id + active_session_id
          |
          v
PostgreSQL (authoritative)
  chat_sessions: session ownership, title, next turn index, fencing token
  chat_turns: user query, allowlisted public response, compact Turn, request id
          ^
          |
Redis SessionStore (coordinator only)
  lease, fencing counter, lock/session metadata
```

Redis 不再作为新聊天历史或 fencing token 的权威来源；新持久化路径不会向 Redis 的 turns 或 requests 写入对话内容。它仍然为每个请求提供多 worker 互斥锁和短期运行元数据，PostgreSQL 分配 fencing token，防止 Redis 状态丢失后 token 回退。

## PostgreSQL 模型

`chat_sessions`：

- `id UUID` 主键；`browser_id_hash`、`game`、`title`、`title_is_custom`、`is_pinned`。
- `next_turn_index` 为服务端分配的单调 turn 序号。
- `active_fencing_token` 由 PostgreSQL 事务严格递增分配；它不依赖 Redis 计数器存活。
- `created_at` / `updated_at` 用于排序和列表展示。

`chat_turns`：

- `session_id` 外键并级联删除；`request_id` 和 `turn_index` 均在会话内唯一。
- `payload_hash` 用于 `(session_id, request_id)` 的幂等重放/冲突判断。
- `user_query` 保存完整用户输入；`public_response` 只保存公开 allowlist 响应。
- `compact_turn` 保存会话记忆所需的 `Turn`，不保存 prompt、原始模型输出、工具参数或内部运行态。

迁移入口：`cd apps/api && uv run alembic upgrade head`。

## API

所有 `/api/v1/chat/sessions` 请求都必须带 `X-DotaMind-Browser-Id: <UUID v4>`。

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `POST` | `/api/v1/chat/sessions` | 创建空会话 |
| `GET` | `/api/v1/chat/sessions` | 列出当前浏览器会话 |
| `GET` | `/api/v1/chat/sessions/{session_id}` | 读取标题和完整持久化 transcript |
| `PATCH` | `/api/v1/chat/sessions/{session_id}` | 重命名或切换置顶状态 |
| `DELETE` | `/api/v1/chat/sessions/{session_id}` | 删除会话及其 turns |

带 `session_id` 的 `/plan` 和 `/plan/stream` 请求同时需要 `request_id` 与浏览器标识。服务端先在 Redis transaction 内取得短期协调锁，再由 PostgreSQL 原子分配严格递增的 fencing token；随后读取历史、运行 Graph，最后在同一 PostgreSQL 事务中完成旧 owner 校验、幂等检查、分配序号、自动首条标题和 turn 写入。

## 前端行为

`apps/chat` 使用 assistant-ui 的 `LocalRuntime`：

1. 首次打开生成并保存 browser UUID；没有会话时创建默认会话。
2. 左侧栏列出、创建、选择、重命名、置顶和删除会话；置顶会话优先显示，当前会话 id 保存到 localStorage。
3. 切换会话时从 transcript 恢复消息，后续流式请求携带 browser/session/request 三个 id。
4. 继续展示阶段、工具、真实 token 和最终结果；成功运行卡自动折叠。

## 失败与安全语义

- 会话 id 必须同时匹配 browser hash；不存在或不属于当前浏览器返回 `404`。
- 缺失/非法 browser id 或 request id 返回 `422`；幂等 hash 冲突返回 `409`。
- PostgreSQL 或 Redis lease 失败直接暴露稳定错误，不回退到另一种聊天存储；Redis 状态重建不会降低 PostgreSQL 的 fencing 校验。
- 删除聊天先取得协调锁，再删除 PostgreSQL 会话和 turns；锁内只清理 Redis 数据键，正常退出释放 lock，清理失败不撤销已完成的 PostgreSQL 删除。

## 后续阶段

登录用户与跨设备同步、搜索/归档、消息级编辑和分支、后台摘要压缩、断线重连与 checkpoint 互操作另行设计，不在 V3.3-1 的兼容承诺内。
