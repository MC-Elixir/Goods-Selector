# Amazon Selector 部署指南

本指南覆盖本地运行、Docker 部署、`.env` 配置、首次登录 cookies、运行选品任务、导出报告和 WebUI 查看结果。

## 甲方本机最小安装

当前交付只要求：

1. 本机已安装 Docker Desktop 与 Google Chrome
2. 项目 `.env` 配置运行所需密钥
3. 在 9222 专用 Chrome 登录卖家精灵插件、Amazon 和 1688
4. 在 Amazon.com 左上角配送地址设置美国邮编（例如 `10004`），确认页面显示美国
   配送城市和邮编后再保存登录态。其他有效美国邮编也可使用；更换客户机或登录态后
   重新检查，避免配送地区影响商品可售状态、价格和搜索结果。

默认不需要填写 `MJJL_API_KEY`、`KEEPA_API_KEY`、`RAINFOREST_API_KEY`。Amazon 不配
Keepa/Rainforest 时走爬虫；卖家精灵市场分析可走浏览器导出。若已购买卖家精灵开放平台
能力，也可设置 `MJJL_TRANSPORT=mcp` 使用官方 MCP 获取市场数据，但插件“1688 找货”
仍是正式供应商发现路径。`SELECTOR_MCP_TOKEN` 由安装脚本自动生成。

Windows 首次安装或更新代码后在项目根目录运行 `./start.ps1 -Build`；日常启动运行
`./start.ps1`，复用已构建镜像。其他系统运行
`docker compose up -d --build amazon-selector`。数据库初始化由容器入口自动完成。
`start.ps1` 不假定 Windows loopback 一定能被 Docker Desktop 转发：它先等待 Windows
`127.0.0.1:9222/json/version`，再从 `amazon-selector` 内通过
`host.docker.internal:9222` 解析当前 CDP WebSocket 并验证端口可达。CDP 任一步失败都会
停止服务并打印分阶段诊断。SellerSprite locator、下载目录或插件会话未就绪时 WebUI
会保留用于完成配置，但脚本明确警告不要开始正式任务。不要为了绕过检查把 9222
裸暴露到局域网或公网。

Windows 下载映射默认由 `start.ps1` 设置为项目下的 `data/imports/sellersprite`。
需要其他目录时，在私有 `.env` 中设置 `SELLERSPRITE_BROWSER_HOST_DOWNLOAD_DIR`
为 Windows 绝对路径；该路径同时提供给 Chrome 和 Compose 的 bind mount。
WebUI 的“目录已确认”字段不会修改宿主机挂载，改变目录后须重新运行启动脚本。
还需在专用 Chrome 的 `chrome://settings/downloads` 中将默认下载目录设置为同一
Windows 目录，并关闭“下载前询问每个文件的保存位置”。卖家精灵扩展下载可能不采用
CDP 设置的目录；应以一次真实导出在容器映射目录中出现且可解析作为下载验收依据。
正式 preflight 必须找到反查关键词与 1688 找货两组 locator，并在专用 Chrome
的 Amazon 页面中观察到已登录的插件面板；检查不会执行导出或消耗找货额度。
定位档的 `product_packaging` 应指向经核验的当前 ASIN 包装信息区。当前中文插件会读取
明确标注的“包装尺寸”和“包装重量”，保存原文、来源和时间后用于物流计算；商品展开
尺寸、两维尺寸或缺项不能补成装箱数据。包装数据缺失时仍保留待核验状态。
在 `/operator` 完成登录和美国配送邮编设置后点击保存登录态，将当前会话同步到后台
Cookie 文件；后续修改配送地址后也需再次保存。

重启 Windows 后先登录桌面、启动 Docker Desktop，再运行 `start.ps1`。容器自动
重启不代表专用 Chrome 已恢复；运行期间不要休眠或关闭该 Chrome。升级前停止
项目服务并备份 `data/` 和 `.env`；备份不能替代目标客户机上的一次真实单商品验收。
运行日志保存在 `data/logs/runtime.log`，按 10 MB 轮转并保留 14 天；Docker 日志每个
服务最多保留 3 个 10 MB 文件。业务节点、结果快照及导出哈希继续保存在 SQLite。

地址：

```text
http://127.0.0.1:8765/operator   # 人工登录 / 验证码 / 续跑
http://127.0.0.1:8765            # 一键研究
http://127.0.0.1:8766/mcp        # 可选 assistant profile / MCP
```

需要代理才能构建镜像时，在宿主机导出 `HTTP_PROXY` / `HTTPS_PROXY`；compose 不再写死本机代理端口。

## 1. 准备 `.env`

`.env.example` 是不含密钥的版本化模板；`.env` 是本机私有文件，不会提交到仓库，也
不会被复制进生产镜像。新 clone 后创建私有配置：

```bash
cp .env.example .env
chmod 600 .env
${EDITOR:-vi} .env
```

不要把真实密钥写回 `.env.example` 或提交 `.env`。

至少配置：

```dotenv
DATABASE_URL=sqlite:///data/amazon_selector.db
MODEL_API_PROVIDER=aliyun_token_plan
ALIYUN_TOKEN_PLAN_API_KEY=你的_sk-sp_key
ALIYUN_TOKEN_PLAN_API_BASE=https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
ALIYUN_TOKEN_PLAN_VISION_MODEL=qwen3-vl-plus
ALIYUN_TOKEN_PLAN_TEXT_MODEL=qwen-plus
ALIBABA_ALLOW_MOCK_SUPPLIERS=false
ENABLE_SCRAPLING_MATCHER=false
LOG_DIR=data/logs
BU_CDP_HTTP=http://host.docker.internal:9222
MJJL_MAX_PRODUCTS_PER_RUN=1
```

`./scripts/start_hermes_client.sh` 会在缺省时自动补上上述非密钥默认值，并生成
`SELECTOR_MCP_TOKEN`。

以后可选（本次交付不需要）：

```dotenv
# KEEPA_API_KEY=          # 不配则 Amazon 走爬虫
# RAINFOREST_API_KEY=     # 不配则 Amazon 走爬虫
# MJJL_API_KEY=           # 不配则市场分析走 9222 Chrome 卖家精灵插件
ALIBABA_APP_KEY=
ALIBABA_APP_SECRET=
ALIBABA_ACCESS_TOKEN=
```

说明：

- 模型 API 至少配置一种：阿里云 Token Plan、阿里云百炼按量付费、PPIO 或 Anthropic。
- Token Plan 的 `sk-sp-` Key 必须与对应地域的 Token Plan Base URL 配套；不要与普通百炼端点混用。
- `KEEPA_API_KEY` / `RAINFOREST_API_KEY` 可作为 Amazon 数据源；不填时默认走爬虫路径。
- `MJJL_API_KEY` 是卖家精灵 HTTP API；本次交付不使用，市场数据来自浏览器导出。
- `MJJL_MAX_PRODUCTS_PER_RUN` 在正式浏览器流程中只作为启用开关：任何正数都会对本次
  Amazon crawler 得到的全部 ASIN 逐一取证；`0` 仅用于离线诊断，不能用于正式任务。
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

一条命令构建并启动唯一必需的 WebUI 服务：

```bash
docker compose up --build -d amazon-selector
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
请先在目标机完成 SellerSprite Phase-0 调查，
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

权限不足与配额耗尽的 selector 不通过人为消耗额度、修改订阅或触发限制来采集；它们
按**首次自然出现时补录**。届时保留提示页面，收集脱敏 DOM 证据，将审查后的 selector
追加到 `data/` 中的本机 locator profile，并重新运行受控验证。

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
