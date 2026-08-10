# Amazon Selector Hermes profile

这是交付给单个甲方的受限 Hermes 0.20.x profile。它只连接本机带 Bearer 鉴权的
Selector MCP，并同时使用工具白名单、Hermes `untrusted` 审批层和业务侧 `confirm`
参数限制写操作。终端、文件、通用浏览器、联网搜索、记忆、定时任务、消息发送和子
Agent 均关闭。

## 安装与启动

先安装官方 Hermes Agent 0.20.x，并在项目 `.env` 中配置好现有选品服务和文本模型。
然后从项目根目录执行：

```bash
./scripts/start_hermes_client.sh
```

脚本会：

1. 生成或复用 `SELECTOR_MCP_TOKEN`，密钥不会打印到终端；
2. 从项目 `.env` 的 PPIO 配置推导 Hermes 模型配置；
3. 安装/更新 `amazon-selector-client` profile；
4. 构建并启动 WebUI 与 MCP sidecar；
5. 打开 Hermes 对话。

如需分步执行：

```bash
python scripts/setup_hermes_client.py --install-profile --start
amazon-selector-client chat
```

人工登录、验证码与续跑统一打开：

```text
http://127.0.0.1:8765/operator
```

## 验收

```bash
curl -i http://127.0.0.1:8766/mcp
# 未带 Authorization 时应返回 401，而不是工具列表。

docker compose --profile assistant ps
amazon-selector-client chat
```

在对话中依次测试“检查选品环境”“列出支持类目”。再要求开始一个 1 件商品的小任务：
Hermes 应先复述影响并请求确认，未确认时不得启动；确认后可启动，重复相同 request_id
不得创建第二个任务。

## 交付边界

- 8765、8766、9222 均只允许本机访问，不要映射到公网。
- `.env`、Hermes profile 的 `.env`、Cookie 文件与 `data/` 不得提交或打包给无关人员。
- 甲方只使用 `amazon-selector-client chat` 和 `/operator`；完整 WebUI 留给运维人员。
- 升级 Hermes 前先在测试机验证。此 profile 固定兼容 `>=0.20.0,<0.21.0`，不要自动跨小版本升级。
