# Amazon Selector 部署指南

本指南覆盖本地运行、Docker 部署、`.env` 配置、首次登录 cookies、运行选品任务、导出报告和 WebUI 查看结果。

## 1. 准备 `.env`

`.env`（以及某些机器上已有的 `.env.example`）是本地私有文件，均不会提交到
仓库，也不会被复制进生产镜像。因此新 clone 的目录**不能假定**存在
`.env.example`，不要直接执行 `cp .env.example .env`。在部署机器手工创建私有配置：

```bash
umask 077
touch .env
${EDITOR:-vi} .env
```

若团队已通过受控渠道提供了该机器上的本地模板，先确认文件存在且内容可信后才可
复制它；不要把含密钥的模板提交到仓库。

至少配置：

```dotenv
DATABASE_URL=sqlite:///data/amazon_selector.db
PPIO_API_KEY=你的_ppio_key
PPIO_API_BASE=https://api.ppio.com/openai
PPIO_MODEL=qwen/qwen3.5-plus
PPIO_TEXT_MODEL=zai-org/glm-5.2
ALIBABA_ALLOW_MOCK_SUPPLIERS=false
ENABLE_SCRAPLING_MATCHER=false
LOG_DIR=data/logs
```

可选配置：

```dotenv
KEEPA_API_KEY=
RAINFOREST_API_KEY=
MJJL_API_KEY=
ALIBABA_APP_KEY=
ALIBABA_APP_SECRET=
ALIBABA_ACCESS_TOKEN=
```

说明：

- `PPIO_API_KEY` 用于视觉识别，正式选品通常必填。
- `KEEPA_API_KEY` / `RAINFOREST_API_KEY` 可作为 Amazon 数据源；不填时默认走爬虫路径。
- `MJJL_API_KEY` 用于卖家精灵市场分析；不填时跳过该分析。
- `ALIBABA_DETAIL_ENRICH_LIMIT=2` 控制每个 Amazon 商品最多打开多少个 1688 详情页补 MOQ、包装尺寸、交期和风险线索。
- `ALIBABA_DETAIL_CACHE_TTL_SECONDS=604800` 控制 1688 详情页补全缓存有效期，缓存落在 `data/cache/1688/offer_details.json`。
- `LOG_DIR=data/logs` 把日志目录放进 `./data` 数据卷，便于备份和排障。
- `ALIBABA_ALLOW_MOCK_SUPPLIERS=false` 是正式部署建议值，避免报告混入 mock 供应商。

## 2. 首次登录 cookies

首次正式运行前，在能弹出浏览器的机器上执行：

```bash
python setup_amazon_login.py
python setup_1688_login.py
```

成功后会生成：

```text
data/amazon_cookies.json
data/1688_cookies.json
```

Docker 部署会把宿主机 `./data` 挂载到容器 `/app/data`，所以容器会直接读取这些 cookies。

如果 Docker 跑在远程服务器，而服务器没有图形界面：在本地电脑完成登录脚本后，把两个 cookies 文件上传到服务器项目目录的 `data/` 下。

## 3. Docker 部署

一条命令构建并启动 WebUI：

```bash
docker compose up --build -d
```

默认只监听宿主机本地：

```text
http://127.0.0.1:8765
```

这是因为 `docker-compose.yml` 使用：

```yaml
ports:
  - "127.0.0.1:8765:8765"
```

因此公司电脑外部默认无法直接访问这个 WebUI。

远程服务器访问建议优先使用 SSH 隧道：

```bash
ssh -L 8765:127.0.0.1:8765 user@服务器IP
```

然后在本地浏览器打开：

```text
http://127.0.0.1:8765
```

如果必须让局域网直接访问，把 `docker-compose.yml` 中端口映射改为：

```yaml
ports:
  - "8765:8765"
```

然后重启，并在公司电脑防火墙放行 TCP 8765：

```bash
docker compose up -d
```

不建议直接暴露到公网：当前 WebUI 是本地工具形态，没有登录鉴权、速率限制或 HTTPS 终止。

持久化目录统一在宿主机 `./data/` 下：

```text
data/amazon_selector.db
data/amazon_cookies.json
data/1688_cookies.json
data/cache/
data/exports/
data/images/
data/logs/
```

容器启动时 entrypoint 会自动创建 `cache/`、`exports/`、`images/`、`logs/`，并执行一次幂等的 `init-db`。

## 4. 本地部署

```bash
pip install -r requirements.txt
playwright install chromium
python main.py init-db
python main.py agent-web
```

打开：

```text
http://127.0.0.1:8765
```

Browser Assistant 是可选能力。Docker 镜像会把 `browser-use` 安装到独立的 `/opt/browser-agent` venv，不污染主 pipeline Python 环境；本地非 Docker 运行时如果需要该功能，可额外执行：

```bash
pip install browser-use
python -m playwright install chromium
```

在 Docker 中运行 Browser Assistant 时，需要让容器连接到一个已启用 remote debugging 的 Chrome/Edge。推荐通过 `.env` 配置稳定 HTTP 入口：

```bash
BROWSER_AGENT_ALLOWED_DOMAINS=amazon.com,1688.com,detail.1688.com,s.1688.com,127.0.0.1,localhost
BU_CDP_HTTP=http://host.docker.internal:9222
```

后端会请求 `${BU_CDP_HTTP}/json/version` 并自动解析当前 `webSocketDebuggerUrl`，因此 Chrome 重启后通常不需要重新配置变化的 `/devtools/browser/<id>`。`BU_CDP_WS=ws://host.docker.internal:9222/devtools/browser/<id>` 仍可作为高级固定端点配置，但不建议作为 Docker 默认配置。

如果未配置可连接浏览器，`browser-use --doctor` 会显示 `chrome running` / `daemon alive` 失败，WebUI 的 Browser Assistant 会返回失败和下一步提示；主选品 pipeline 不受影响。

## 5. SellerSprite 反查关键词浏览器导出（默认关闭）

SellerSprite 浏览器导出不是通用 Browser Assistant 的替代品。它只针对一个 Amazon
**US** ASIN，且只有在用户的可见、已登录 SellerSprite Chrome profile 中才允许
运行。部署后默认保持：

```dotenv
SELLERSPRITE_BROWSER_ENABLED=false
```

不要在未完成 Phase-0 调查时启用它。仓库没有内置、示例或推测的 locator profile；
请先按 [SellerSprite Phase-0 调查记录](research/sellersprite_dom_investigation.md)
收集真实且脱敏的 DOM、扩展版本、导出表头、登录/验证码/权限提示，以及独立控制
的 Windows 宿主机与 Docker 容器下载目录映射。禁止记录 cookies、账号、密钥和
含个人数据的截图。

在用户已登录、明确批准，并且本机审查后的 locator profile 与下载目录映射均已
验证后，优先通过正式 WebUI 的 SellerSprite 卡片保存配置。它将安全配置写入挂载的
`data/sellersprite_browser_config.json`，重建容器后仍然可用；文件不保存 Windows
绝对路径、cookie、账号或密钥。以下环境变量只作为非 UI 部署覆盖项：

```dotenv
SELLERSPRITE_BROWSER_ENABLED=true
SELLERSPRITE_BROWSER_LOCATOR_PROFILE_PATH=/app/data/<your-reviewed-profile>.json
SELLERSPRITE_BROWSER_DOWNLOAD_DIR=/app/data/imports/sellersprite
SELLERSPRITE_BROWSER_HOST_DOWNLOAD_DIR=<your-separately-controlled-windows-directory>
BU_CDP_HTTP=http://host.docker.internal:9222
```

这里的尖括号是占位符，不能作为路径、映射或 locator profile 使用。不要通过
Docker 默认端口以外的 WebUI 入口运行：正式服务仍是
`http://127.0.0.1:8765`。

受控 live E2E 需要用户**明确**将 `SELLERSPRITE_E2E=1` 传入该一次测试；它不是
持续启用自动化的开关。建议在用户在场时运行：

```bash
docker compose exec -T -e SELLERSPRITE_E2E=1 amazon-selector \
  pytest tests/e2e/test_sellersprite_extension.py -q -s
```

每次导出在单次 CDP 附着生命周期内使用 `Browser.setDownloadBehavior` 配置下载目录，
不会修改 Chrome 的永久下载偏好。若结果是 `SELLERSPRITE_LOGIN_REQUIRED`、
`SELLERSPRITE_PERMISSION_REQUIRED`、`SELLERSPRITE_QUOTA_EXCEEDED` 或 `CAPTCHA`，
立即停止。它们是终止状态，不可自动重试或绕过；不得把这种状态当作 E2E 成功。

## 6. 运行选品

通过 WebUI 按钮运行：

1. 打开 WebUI。
2. 确认 Preflight 中 `.env`、cookies、数据库、导出目录状态。
3. 输入 `category`、`marketplace`、`limit`。
4. 点击运行按钮。
5. 在 Recent Runs / Results 中查看结果和下载 Excel。

通过 Docker 命令运行：

```bash
docker compose run --rm amazon-selector run --category "Home & Kitchen" --marketplace US --limit 20
docker compose run --rm amazon-selector smoke-run --category "Home & Kitchen" --marketplace US --limit 1
```

通过本地命令运行：

```bash
python main.py run --category "Home & Kitchen" --marketplace US --limit 20
python main.py smoke-run --category "Home & Kitchen" --marketplace US --limit 1
```

## 7. 查看报告和 Dashboard

每次运行会导出到：

```text
data/exports/
```

主要文件：

```text
data/exports/candidates_*.xlsx
data/exports/candidates_*.json
data/exports/reports/*.md
```

查看方式：

- WebUI Dashboard：打开 `http://127.0.0.1:8765`，在 Recent Runs / Results 中查看历史结果。
- Excel：在 WebUI 点击下载，或直接打开 `data/exports/candidates_*.xlsx`。
- JSON：用于程序化复核或后续分析。
- Markdown：单个候选商品的详细报告在 `data/exports/reports/`。

## 8. 常用运维命令

```bash
docker compose ps
docker compose logs -f amazon-selector
docker compose restart amazon-selector
docker compose down
```

### 全量回归（挂载当前源码）

正式 WebUI 使用 `docker compose up -d --build amazon-selector`，并仍通过
`http://127.0.0.1:8765` 提供服务。该生产镜像有意通过 `.dockerignore` 排除
`README.md`、`Dockerfile`、`docker-compose.yml` 等仓库根文件；因此不要把
`docker compose run --rm amazon-selector pytest tests/ -q` 当成完整源码回归，它会
使依赖这些静态文件的测试失去运行条件。

先构建当前测试镜像，再把可见工作区只读挂载到容器，并用独立临时数据目录运行：

```bash
docker compose build amazon-selector

TEST_DATA="$(mktemp -d)"
cleanup() {
  docker run --rm -v "$TEST_DATA:/data" --entrypoint sh amazon-selector:dev \
    -lc 'rm -rf /data/* /data/.[!.]* /data/..?*' >/dev/null 2>&1 || true
  rmdir "$TEST_DATA" 2>/dev/null || true
}
trap cleanup EXIT

docker run --rm \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e LOG_DIR=/app/data/logs \
  -v "$PWD:/app:ro" \
  -v "$TEST_DATA:/app/data" \
  -w /app \
  --entrypoint pytest \
  amazon-selector:dev tests/ -q -s -p no:cacheprovider
```

这条命令不读取 Compose 的本地 `.env`，也不会写入真实 `data/`。`cleanup` 使用
容器删除临时目录中的 root 所有者文件，避免普通宿主机用户在测试后无法清理它。

## 9. 日志和长任务排障

日志分三层：

```text
WebUI 当前任务事件：Run Agent 页面 / Recent Jobs 展开的事件列表
任务状态文件：data/logs/agent_jobs.json
详细运行日志：docker compose logs -f amazon-selector
```

常用查看命令：

```bash
# 实时看完整流水线日志，包含 Amazon、1688、LLM 验证、超时原因
docker compose logs -f amazon-selector

# 只看最近 200 行
docker compose logs --tail=200 amazon-selector

# 看 WebUI 任务状态、失败原因和每个 ASIN 进度
python -m json.tool data/logs/agent_jobs.json | less

# 看最近导出的结果
ls -lt data/exports | head
```

如果要长时间运行、开启 LLM 验证、或一次跑较大的 `limit`，建议在 `.env` 中使用长任务预算：

```bash
PIPELINE_CRAWL_TIMEOUT_SECONDS=3600
PIPELINE_MATCH_TIMEOUT_SECONDS=43200
PIPELINE_PROFIT_TIMEOUT_SECONDS=7200
PIPELINE_MARKET_TIMEOUT_SECONDS=14400
PIPELINE_SCORE_TIMEOUT_SECONDS=7200
PIPELINE_EXPORT_TIMEOUT_SECONDS=3600
LOG_DIR=data/logs
```

修改 `.env` 后需要重启容器让环境变量生效：

```bash
docker compose up -d --force-recreate
```

如果 preflight 提示 cookies 失效，重新执行登录脚本并覆盖 `data/amazon_cookies.json` 或 `data/1688_cookies.json`。
