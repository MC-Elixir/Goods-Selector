---
name: goods-selector-deployment
description: Deploy or verify goods-selector in its target environment, including Chrome and SellerSprite readiness.
---

# goods-selector 部署与验收

从仓库根目录工作。根据用户请求确定目标机器、版本及验收范围；“拉取最新代码”时先检查已有工作并安全同步指定分支，不写死历史分支或提交。部署请求包含目标服务的必要启动和健康检查，但不自动授权真实选品、消耗额度或破坏性数据操作。

## 操作入口

- WebUI：读取 `docs/DEPLOYMENT.md` 中适用平台的安装/启动段，并核对 `start.ps1` 与 `docker-compose.yml`。正式服务为 Compose 的 `amazon-selector`；本地 Python 备用运行只证明调试路径有效。
- 可选 Hermes/MCP：需要时才读取 `deployment/hermes/amazon-selector-profile/README.md`、`scripts/setup_hermes_client.py` 和相应配置。普通 WebUI 无需为此安装完整客户端。
- 修改部署实现时，使用 [验证 Skill](../goods-selector-validation/SKILL.md) 中的部署回归门禁。升级前按当前部署文档停止目标服务并备份私有配置和数据。

## 验收结果

- 确认实际目标容器及 WebUI HTTP 可用。端口、入口和环境变量从当前配置发现，不以进程启动代替健康检查。
- 分别验证宿主与容器调用环境中的 CDP；宿主可达不足以证明容器可达。保持专用 Chrome 的本机访问边界，不将 9222 暴露到所有网卡。
- 检查 preflight 和正式路径所需的 SellerSprite 插件会话、locator 及下载目录就绪；按部署文档核对美国配送区域和登录态同步。登录、验证码和权限问题保留人工处理路径，阻塞时继续独立的诊断与准备。
- 启用 MCP 时验证未认证拒绝、认证初始化及当前精确工具白名单，保留 Bearer、`confirm=true` 和持久化 `request_id` 合同。不要记录密钥、Cookie 或恢复令牌，也不以固定工具数量代替合同检查。
- 只有获授权的真实任务成功并产出可审计证据工作簿，才算真实业务验收；真实导出还应验证文件落入实际挂载目录且可解析。保持 Amazon → SellerSprite → 插件 1688 来源及 No-Mock 边界；人工解除后恢复原任务，避免重复消耗。

分别报告服务健康、业务就绪、真实任务验收及阻塞。失败时保留必要日志与版本信息，明确目标环境剩余工作；不将替代路径成功报告为正式部署完成。
