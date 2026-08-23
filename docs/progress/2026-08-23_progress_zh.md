# 2026-08-23 进度快照

## 16:09 — VLESS 数据源出口迁移准备

### 已完成

- 生产 Compose 增加内部 `vless-proxy` sing-box sidecar；API 通过标准 `HTTP_PROXY` / `HTTPS_PROXY` 使用其内部 HTTP 入站，`NO_PROXY` 保持 Compose 本地服务直连。
- 新增不含凭据的 sing-box 客户端示例；实际 `deploy/sing-box.client.json` 设为忽略文件，仅保留在部署服务器并使用 root 600 权限。
- 106.52.89.125 的实际 API 容器复现 PandaScore 直连慢路径：Series 100 条约 20.27 秒，赛程串行约 14.62 秒，其中 `past` 约 11.44 秒；容器没有任何代理环境变量。
- 96.126.130.87 的 VLESS 服务端已存在；106 的私有客户端配置 JSON 已写入并通过 JSON 语法检查，生产 Compose 已备份后完成结构校验。

### 验证

- 本地 `compose.prod.yml` Compose 结构检查与 `deploy/sing-box.client.example.json` JSON 检查通过。
- 106 生产 Compose `config -q` 通过；私有客户端配置为 `root:root`、600。

### 当前限制

- `ghcr.io/sagernet/sing-box:v1.13.16` 镜像正在 106 后台下载；sidecar 尚未就绪，API 尚未重建，WireGuard 两端均未停止或删除。
- sidecar 连通性、API 经 VLESS 的 PandaScore 延迟复测与 WireGuard 清理必须在镜像就绪后顺序完成。

## 16:21 — VLESS 出口生效与 WireGuard 退役

### 已完成

- 由于 106 从 GHCR 拉取 sing-box 镜像停滞，改为从 96 已运行的 sing-box 获取经 SHA-256 校验的静态二进制，并基于 106 已存在的 `dotamind-api` 镜像本地构建 `dotamind-vless-proxy:local` sidecar；不再依赖外部镜像拉取。
- `vless-proxy` 在 Compose 内网运行且没有发布公网端口；API 重建后由标准 `HTTP_PROXY` / `HTTPS_PROXY` 指向该 sidecar。
- 停止并禁用 106.52.89.125 与 96.126.130.87 的 `wg-quick@wg0`，删除已核对的 `wg0` 配置、full-tunnel 配置及 WireGuard 密钥。

### 验证

- API 容器经 VLESS 预切换四请求：Series 100 条 2.58 秒、upcoming 0.37 秒、running 0.68 秒、past 1.20 秒，总计 4.83 秒。
- API 重建后仅依赖环境代理的同一四请求总计 5.61 秒；确认运行时环境含 `HTTP_PROXY`、`HTTPS_PROXY` 与 `NO_PROXY`。
- WireGuard 清理后：两台主机均无 `wg0` 接口；96 的 `sing-box-vless` 为 active；106 的 API 与 `vless-proxy` 均为 Up；API 的 Series 100 条复测为 3.40 秒、HTTP 200。

### 已知边界

- 部署侧 `deploy/sing-box/sing-box` 与 `deploy/sing-box.client.json` 均为忽略的服务器资产，不进入 Git；更新 sing-box 时须重新校验二进制来源与版本。

## 16:38 — PandaScore 出口排查与 VLESS 切换技术记录

### 已完成

- 新增 `docs/technical/pandascore_egress_migration_2026-08-23.md`，集中记录工具调用方式、容器内直连复现、VLESS sidecar 结构、镜像拉取受阻后的本地构建方案、切换前后延迟、WireGuard 退役范围和运维边界。
- 在 `docs/README.md` 技术参考中登记该记录；不在文档中写入 VLESS UUID、Reality 参数、私有 JSON 或静态二进制。

### 验证

- 检查技术记录与文档导航的相对链接；中英文进度快照新增相同结构的本节。
