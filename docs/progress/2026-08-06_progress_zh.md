# DotaMind 进度快照 — 2026-08-06

## 20:52 — 腾讯云单机容器部署

### 已完成

- 新增 FastAPI 与 Next.js 生产 Dockerfile、构建忽略文件、Nginx 同源反向代理和 `compose.prod.yml`；公网只发布 80 端口，PostgreSQL、Redis、API 与 Chat 均保留在 Docker 内网。
- 从 `apps/api/uv.lock` 导出 `requirements.prod.txt`，使用固定版本生产依赖；腾讯云构建通过内网 PyPI 镜像安装依赖，规避 GHCR/PyPI 公网下载异常缓慢。
- 将本地 `v3.3` 当前提交和本地 `.env` 通过 SSH 部署到 `159.75.78.201:/opt/dotamind`；远程 `.env` 权限为 `600`，临时传输副本已删除。
- Nginx 将 `/api`、`/health`、`/docs`、`/openapi.json` 与 `/debug` 转发到 FastAPI，其余请求转发到 Next.js；Chat 构建使用相对 API 地址。
- README 增加 Compose 部署、验证、依赖锁导出与 HTTP/TLS 边界说明。

### 已验证

- `docker compose -f compose.prod.yml config --quiet`：通过。
- API 与 Chat 生产镜像构建通过；Next.js production build 与 TypeScript 检查通过，npm audit 为 0 vulnerabilities。
- Alembic 从空 PostgreSQL 成功升级到 `20260805_03`；PostgreSQL 与 Redis healthcheck 均为 healthy，五个容器持续运行。
- 公网 `GET /`、`GET /health`、`HEAD /docs` 均返回 HTTP 200。
- Chat Session 创建、列表与删除冒烟通过；清理后 `chat_sessions` 行数为 0。
- 最小 `/api/v1/plan` 请求完成真实 DeepSeek 调用，provider 三次返回 HTTP 200，Agent Graph 正常收口为 `clarification_required` 且无运行错误。

### 边界

- 当前部署地址为 `http://159.75.78.201`，尚未配置域名与 HTTPS；正式公网生产前需要 TLS 终止。
- PostgreSQL 默认口令只在 Docker 内网使用，Compose 已支持通过 `DOTAMIND_POSTGRES_PASSWORD` 覆盖；持久生产数据前应设置随机强口令。
- 本地 `v3.3` 分支未推送到 GitHub，本次部署使用 SSH 直传；本轮未提交或推送部署文件。

## 21:08 — 公网 HTTP 前端启动修复

### 已完成

- 修复 Chat 在公网 HTTP 非安全上下文中直接调用 `crypto.randomUUID()` 导致启动崩溃的问题；新增 UUID v4 工具，在平台 API 不可用时使用 `crypto.getRandomValues()` 并设置 RFC 4122 版本与变体位。
- Browser ID 与 Chat Run request ID 统一使用该工具；新增原生路径和兼容路径的单元测试。
- 重新构建并部署 `chat` 镜像，重启 Nginx 以刷新上游容器解析；API、数据库和现有数据未变更。

### 已验证

- Chat：`npm run test` 为 3 个测试文件、6 个测试全部通过；`npm run lint` 与 `npm run build` 通过。
- 公网 `GET /` 与 `GET /health` 均返回 HTTP 200，五个 Compose 容器持续运行，PostgreSQL 与 Redis 为 healthy。
- Edge 150 通过 `http://159.75.78.201/` 加载新静态资源后，两次请求 `/api/v1/chat/sessions` 均返回 HTTP 200，确认前端已越过原先的初始化崩溃点。

### 边界

- 该修复使当前 HTTP 地址可用，但浏览器仍会标记连接“不安全”；域名与受信任 HTTPS 证书仍是正式公网发布前的独立部署工作。
