# Amazon Selector

Amazon Best Seller 选品自动化系统。给定一个 Amazon 类目 → 爬取 BSR 榜单产品 → 视觉识别 + 1688 爬虫匹配货源 → 利润预测 → 6 维度评分 → 硬性筛选 → 排名 → 导出候选选品池（Excel / Markdown / JSON）。

当前兼容入口仍是 7 阶段 deterministic pipeline；Phase 3 的 `--mode agent`
有限状态循环尚未实现。最新的 Phase 1–2 验证结果及外部数据阻塞见
[审计报告](docs/audits/2026-07-10-phase1-phase2-results.md)。

## 快速开始

```bash
# 所有命令在 amazon_selector/ 目录下执行
cd amazon_selector

# 1. 安装依赖
pip install -r requirements.txt
playwright install chromium          # Amazon / 1688 爬虫需要

# 2. 配置环境变量（参考 .env 已有的模板，至少填 PPIO_API_KEY 用于视觉识别）
#    首次跑前需登录拿 cookies（见下"登录"小节）

# 3. 初始化数据库（SQLite，建 6 张表）
python main.py init-db

# 4. 跑完整流水线
python main.py run --category "Home & Kitchen" --limit 10
python main.py run --category "Toys & Games" --limit 10 --marketplace US

# 5. 跑测试（纯单元测试，不联网、不需 API key）
pytest tests/
```

## Agent WebUI

本项目现在提供一个本地 Agent 控制台，把"环境 + 工具 + 系统提示 + 循环"落到可操作界面。正式使用默认走 Docker，只保留 `8765` 这一套运行方式：

```bash
docker compose up -d --build amazon-selector
# 打开 http://127.0.0.1:8765
```

`python main.py agent-web` 仅用于本机调试备用，不建议作为日常启动方式，否则很容易和 Docker 同时开出两套服务。

WebUI 能做：

- 运行前 preflight：检查 PPIO、Amazon cookies、1688 cookies、数据库、导出目录、1688 cooldown。
- 启动 sourcing agent run：填写 category / marketplace / limit，默认 No-Mock 模式，避免正式结果混入 mock 供应商。
- 查看 Recent Runs：读取 `data/exports/candidates_*.json` / `.xlsx`。
- 查看和搜索历史候选商品：按 ASIN、标题、供应商搜索，并下载对应 Excel。
- 保存/取消保存候选商品：保存状态写入 `data/agent_saved_items.json`。
- Browser Assistant（可选）：在 Settings 中通过本地 `browser-use` 辅助检查 1688 登录态、诊断 Amazon/1688 页面、补采 1688 详情字段；不替换主 pipeline 爬虫。

Browser Assistant 默认只允许访问 `amazon.com`、`1688.com`、`detail.1688.com`、`s.1688.com`、`127.0.0.1`、`localhost`。Docker 镜像会把 `browser-use` 安装到独立的 `/opt/browser-agent` venv，避免影响主 pipeline 依赖。本地非 Docker 运行时如需启用：

```bash
pip install browser-use
python -m playwright install chromium
```

可通过 `.env` 覆盖白名单：

```bash
BROWSER_AGENT_ALLOWED_DOMAINS=amazon.com,1688.com,detail.1688.com,s.1688.com,127.0.0.1,localhost
```

Docker 中 `browser-use` 已内置，但它需要连接到一个已启用 remote debugging 的 Chrome/Edge。若 Browser Assistant 返回 `DevToolsActivePort not found`，请在宿主机或独立浏览器容器启动 Chrome remote debugging，并优先配置稳定 HTTP 入口：

```bash
BU_CDP_HTTP=http://host.docker.internal:9222
```

系统会从 `${BU_CDP_HTTP}/json/version` 自动解析当前 `webSocketDebuggerUrl`，所以 Chrome 重启后通常不需要重新复制 `/devtools/browser/<id>`。`BU_CDP_WS=ws://.../devtools/browser/<id>` 仍可用于高级固定端点，但 browser id 可能随 Chrome 重启变化。

### SellerSprite 反查关键词浏览器导出（受控功能）

这项功能与上面的通用 Browser Assistant 相互独立：它只处理一个 Amazon **US**
ASIN 的 SellerSprite 可见反查关键词导出。默认**关闭**，且仓库不会提供或猜测
SellerSprite locator profile。当前真实页面调查状态见
[docs/research/sellersprite_dom_investigation.md](docs/research/sellersprite_dom_investigation.md)。

启用前必须由已登录 SellerSprite 的用户在可见 Chrome 中亲自确认，并先完成真实
DOM、导出表头、扩展版本和 Windows 宿主机到 Docker 下载目录映射的脱敏记录。把
经过审查的 locator profile 保存在本机受控目录，不要提交 cookies、账号、密钥或
profile 内容到仓库。常态配置保持：

```dotenv
SELLERSPRITE_BROWSER_ENABLED=false
```

在用户明确批准且上述记录完成后，才在本地 `.env` 中设置真实路径与 CDP 入口；
以下名称是配置项，不是可直接照抄的 profile 或宿主机路径：

```dotenv
SELLERSPRITE_BROWSER_ENABLED=true
SELLERSPRITE_BROWSER_LOCATOR_PROFILE_PATH=/app/data/<your-reviewed-profile>.json
SELLERSPRITE_BROWSER_DOWNLOAD_DIR=/app/data/imports/sellersprite
SELLERSPRITE_BROWSER_HOST_DOWNLOAD_DIR=<your-separately-controlled-windows-directory>
BU_CDP_HTTP=http://host.docker.internal:9222
```

现场验证只允许在用户显式设置 `SELLERSPRITE_E2E=1` 后运行；该变量是一次性
用户批准，不是日常开关。遇到 `SELLERSPRITE_LOGIN_REQUIRED`、
`SELLERSPRITE_PERMISSION_REQUIRED` 或 `CAPTCHA` 时，这些都是终止状态：停止，
把 `SELLERSPRITE_BROWSER_ENABLED` 设回 `false`，不要重试、绕过或伪造成功。

## Docker

本项目支持 Docker 部署，**正式跑默认禁用 mock 供应商**（`alibaba_allow_mock_suppliers` 默认 False，compose 环境变量再次硬设 `false`）。
完整部署流程见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)，包含 `.env` 配置、首次登录 cookies、Docker 启动、命令或 WebUI 按钮运行选品、Excel/JSON/Markdown 报告和 Dashboard 查看结果。

```bash
# 一条命令构建并启动 Agent WebUI（端口默认只映射到本机 127.0.0.1:8765）
docker compose up -d --build amazon-selector
# 打开 http://127.0.0.1:8765

# 一次性 CLI 任务（command 会被替换；entrypoint 仍会先跑 init-db）
docker compose run --rm amazon-selector run --category "Home & Kitchen" --limit 50
docker compose run --rm amazon-selector init-db
docker compose run --rm amazon-selector smoke-run --category "Home & Kitchen" --limit 1

# 全量回归：生产镜像有意不包含 Dockerfile、README 等仓库根文件，
# 因此需要把当前源码只读挂载进隔离容器（完整命令见 docs/DEPLOYMENT.md）。
docker compose build amazon-selector
TEST_DATA="$(mktemp -d)"
cleanup() {
  docker run --rm -v "$TEST_DATA:/data" --entrypoint sh amazon-selector:dev \
    -lc 'rm -rf /data/* /data/.[!.]* /data/..?*' >/dev/null 2>&1 || true
  rmdir "$TEST_DATA" 2>/dev/null || true
}
trap cleanup EXIT
docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -e LOG_DIR=/app/data/logs \
  -v "$PWD:/app:ro" -v "$TEST_DATA:/app/data" -w /app --entrypoint pytest \
  amazon-selector:dev tests/ -q -s -p no:cacheprovider
```

数据持久化：`./data:/app/data` 卷挂载，SQLite 数据库、缓存、cookies、导出文件、日志都落在这里。首次启动时 entrypoint 会自动创建 `cache/`、`exports/`、`images/`、`logs/` 并跑 `init-db` 建表。

环境变量：参考 `.env.example`（本地文件，未入库）填好 `.env`，至少需要 `PPIO_API_KEY`（视觉识别）。Amazon/1688 爬虫需要 cookies——在宿主机跑 `setup_amazon_login.py` / `setup_1688_login.py` 生成后放入 `data/`，容器通过卷挂载读取。关键变量：`PPIO_API_KEY`（视觉识别，必需）、`KEEPA_API_KEY`/`RAINFOREST_API_KEY`（Amazon API 抓取，可选，否则走 scrapling）、`MJJL_API_KEY`（卖家精灵市场分析，可选）、`ALIBABA_DETAIL_ENRICH_LIMIT=2`（每个商品最多补全的 1688 详情候选数）、`LOG_DIR=data/logs`（日志目录）、`ALIBABA_ALLOW_MOCK_SUPPLIERS=false`（正式跑保持 `false`）。

本机调试备用入口：

```bash
python main.py agent-web
```

这个入口仅用于本机调试，例如临时排查静态页面或接口，不作为正式使用路径。

远程访问：默认 `docker-compose.yml` 使用 `127.0.0.1:8765:8765`，外部电脑无法直接访问。公司内网访问建议优先用 VPN/SSH 隧道；如果要开放到局域网，把端口映射改成 `"8765:8765"`，并在公司电脑防火墙放行 8765。当前 WebUI 没有登录鉴权，不建议直接暴露公网。

## 一次性登录（首次使用必做）

Amazon 与 1688 都需要登录态 cookies 才能稳定爬取（否则被反爬弹到登录页）：

```bash
python setup_amazon_login.py     # 弹浏览器手动登录 Amazon → 存 data/amazon_cookies.json
python setup_1688_login.py       # 弹浏览器手动登录 1688  → 存 data/1688_cookies.json
```

cookies 会过期（通常数天~两周）。正式 no-mock 模式下，1688 登录或 TMD
风控会使该候选失败关闭或进入人工处理，不会以 mock 供应商替代。届时重跑对应
登录脚本刷新即可。

## 7 阶段流水线

```
main.py run --category --limit --marketplace
  └─ pipeline/orchestrator.py::run_pipeline
       1. crawl    crawlers/amazon_bsr.py      Amazon BSR 榜单 → ProductDTO（Scrapling 抗检测后端，prodDetTable 选器）
       2. match    matchers/__init__.py        视觉识别→Playwright 1688 爬虫→启发式+LLM 验证
       3. profit   analyzers/profit_model.py    6 项成本 + 净利率/净利润预测
       4. market   analyzers/maijiajingling.py  卖家精灵市场分析（需 MJJL_API_KEY，无则跳过）
       5. score    analyzers/scorer.py          6 维度评分 + 硬性筛选
       6. filter   pipeline/filters.py          按总分+净利润排名
       7. report   reports/exporter.py          Excel / Markdown / JSON 导出
```

**阶段失败策略**：Stage 1（爬取）失败则中止整次运行；其余阶段按产品逐个失败并继续——某产品匹配/利润/评分失败只是拿到空数据、被硬筛淘汰。

## 目录结构

```
amazon_selector/
├── main.py                 # CLI 入口（init-db | run）
├── config/                 # settings.py(pydantic) + profit_params.yaml + scoring_weights.yaml
├── crawlers/               # Amazon BSR 采集（_amazon_extractors 共享选器 + scrapling/playwright 后端）
├── matchers/               # 1688 货源匹配（vision + playwright 爬虫 + verifier）
├── analyzers/              # profit_model / scorer / maijiajingling(卖家精灵)
├── pipeline/               # orchestrator(7阶段编排) + filters(排名)
├── reports/                # exporter(Excel/Markdown/JSON)
├── db/                     # SQLAlchemy 6 表 + session
├── tests/                  # pytest（181 passed）
├── data/                   # 缓存、cookies、导出文件、SQLite（.gitignore，不入库）
├── docs/                   # PRD / database_schema / scoring_spec / 选品参考
├── STATUS.md               # 当前状态 + 已知问题 + 下一轮计划
├── CHANGELOG.md            # 变更日志（Keep a Changelog）
└── SHOWCASE.md             # 展示文档（架构图 + 测试结果 + 成果指引）
```

## 关键设计

- **所有可调参数在 YAML**：`config/profit_params.yaml`（成本率）+ `config/scoring_weights.yaml`（评分权重+硬筛阈值），调参不改代码。评分权重必须和=1.0，由 `test_weights_sum_to_one` 强制。
- **Snapshot 模式**：`ProfitSnapshot`/`Score` 追加写入，携带当时的 YAML 快照 JSON，历史决策可回放。
- **缓存**：diskcache 24h TTL，Amazon 同 ASIN/BSR 页回放秒出；验证码命中时删缓存避免污染。
- **正式 no-mock 失败关闭**：Playwright 搜索或详情页被登录、captcha、TMD
  风控拦截时，不把拦截页解析成 offer，也不让 mock supplier 进入候选、持久化或导出。
- **证据门禁**：新 sourcing slice 生成 12 类去品牌查询，保存查询尝试，抓取候选
  详情并做结构化与双图验证；缺失关键价格、MOQ、尺寸、重量、需求或竞争证据时
  只能输出人工复核、拒绝或数据不足，不能强推荐。

## 文档

- [SHOWCASE.md](SHOWCASE.md) — 展示文档：系统介绍、架构图、测试结果、成果文件指引
- [STATUS.md](STATUS.md) — 当前状态、已知问题、下一轮计划
- [CHANGELOG.md](CHANGELOG.md) — 版本变更日志
- [docs/PRD.md](docs/PRD.md) — 产品需求文档
- [docs/scoring_spec.md](docs/scoring_spec.md) — 评分维度公式与示例
- [docs/database_schema.md](docs/database_schema.md) — 数据库表设计
