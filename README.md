# Amazon Selector

Amazon Best Seller 选品自动化系统。给定一个 Amazon 类目 → 爬取 BSR 榜单产品 → 视觉识别 + 1688 爬虫匹配货源 → 利润预测 → 6 维度评分 → 硬性筛选 → 排名 → 导出候选选品池（Excel / Markdown / JSON）。

当前兼容入口仍是 7 阶段 deterministic pipeline；Phase 3 的 `--mode agent`
有限状态循环尚未实现。

## 四类户外产品精准寻源

正式匹配已为 `Outdoor Storage`、`Patio Heater`、`Patio Furniture Sets`、
`Patio Umbrellas & Shade` 启用专用品类合同：Amazon 详情证据会归一化为容量、尺寸、
BTU/功率、件数、组件、伞径、GSM、材质和整品/配件关系；随后执行 12 类去品牌 1688
查询并补全详情。只有关键参数无冲突、价格/MOQ/功能/商品类型有可信来源，且明确属于
生产厂家时，供应商才以 `keep` 进入利润和市场评分。贸易商、规格冲突和证据不足项分别
进入拒绝或人工复核，并保留完整查询与匹配证据。

详细字段合同、判定规则、评估口径和配置见
[四类户外产品自动寻源合同](docs/target-category-sourcing-contract.md)。合成合同金标可直接回归：

```bash
python3 -m benchmarks.evaluate_target_contract
```

真实历史案例尚未人工标注，因此真实 P@1/P@5 和 false-match rate 当前保持 `NULL`，不以
合成合同集的 100% 回归结果冒充线上搜索准确率。

## 快速开始

```bash
# 所有命令在 amazon_selector/ 目录下执行
cd amazon_selector

# 1. 安装依赖
pip install -r requirements.txt
playwright install chromium          # Amazon / 1688 爬虫需要

# 2. 配置环境变量（参考 .env 已有的模板，至少填 PPIO_API_KEY 用于视觉识别）
#    首次跑前需登录拿 cookies（见下"登录"小节）

# 3. 初始化数据库（SQLite，自动应用版本化迁移）
python main.py init-db

# 4. 跑完整流水线
python main.py run --category "Home & Kitchen" --limit 10
python main.py run --category "Toys & Games" --limit 10 --marketplace US

# 如进程中断，可继续同一个 run_id（不会创建新 Run）
python main.py resume-run --run-id 123

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

### 单甲方自然语言入口（Hermes）

本项目为单个甲方提供了一个受控 Hermes 入口。结论是：当前阶段不重新开发 Agent
壳，也不接飞书，采用 **Hermes 0.20.x + 本项目专用 MCP sidecar + 极简人工处理页**。
现有 pipeline、SQLite 和导出逻辑不变，Hermes 只负责对话和调用 19 个经过白名单审查
的选品工具。

```bash
# 前提：已经按 Hermes 官方方式安装 0.20.x
chmod +x scripts/start_hermes_client.sh
./scripts/start_hermes_client.sh
```

一键脚本会准备密钥、安装 `amazon-selector-client` profile、启动 WebUI/MCP，并进入
中文对话。人工登录、验证码或任务续跑时打开：

```text
http://127.0.0.1:8765/operator
```

安全边界：MCP 只监听 `127.0.0.1:8766` 并要求 Bearer Token；Hermes profile 禁用
终端、文件、通用浏览器、搜索、记忆、定时任务、消息和委派；MCP 再做精确工具白名单；
所有写操作同时经过 Hermes `untrusted` 审批和 `confirm=true` 业务确认；启动任务固定
Amazon US、No-Mock，先过 preflight，并使用持久化 request_id 防止重复下单式执行。

详细安装、验收与交付边界见
[Hermes profile 说明](deployment/hermes/amazon-selector-profile/README.md)。

选型原因：Hermes 已提供 profile distribution、中文桌面/CLI、HTTP MCP、Header 鉴权、
工具 include 白名单和不可信 MCP 审批，适合目前“一个客户、尽快可用”的阶段；Pi 的
界面和扩展能力很强，但定位更偏开发者编码 TUI，需要另外开发 TypeScript extension、
业务确认与交付壳；自研 Agent 的可控性最高，但此时要自行承担会话、工具调度、审批、
升级和客户端体验，收益不足。等出现多租户、品牌化桌面端、细粒度审计/计费或离线部署
要求，再把当前 MCP 契约复用到自研壳中。

### 甲方受控试用：一键完整研究

WebUI 默认首页为“一键研究”。试用前在 9222 专用 Chrome 中打开目标 Amazon US
类目页或搜索列表，并等待卖家精灵表格加载；随后选择相同类目/英文关键词并点击
“开始完整研究”。同一个可恢复 Job 会依次完成：

1. 检查 Chrome、卖家精灵、Amazon 与 1688 登录态；
2. 自动导出当前列表的真实卖家精灵数据，汇总卖家并计算 0–100 研究评分；
3. 把排名靠前且带有效 ASIN 的候选直接送入 1688 找货、利润与候选评分，不再二次抓取 Amazon；
4. 交付“市场汇总 Excel/JSON”和“选品结果 Excel/JSON”；即使 0 个商品通过硬筛选，
   也会输出包含真实供应商证据与淘汰原因的复核报告，不会把淘汰项冒充候选。

遇到登录、权限、额度或验证码时，任务会保留进度并显示“我已处理，继续任务”；
任务结束后页面会显示一份约 20 秒可完成的体验反馈表，记录到本机
`data/trial_feedback.json`。页面下方“试用验收”会自动汇总，并只在以下门槛全部
通过后显示“可进入安装包”：

- 至少 3 次已经结束的一键研究任务反馈；
- “Amazon 类目列表”和“Amazon 搜索列表”两种入口都至少完成一次真实试用；
- 至少 2/3 的任务完成市场报告与选品结果两组文件交付；
- 平均操作顺畅度不低于 4.0 / 5；
- 平均报告帮助度不低于 4.0 / 5；
- 至少 2/3 的反馈愿意继续使用；
- 至少 2/3 的反馈没有主要卡点。

反馈接口会核对 Job 确实存在且已经结束，运行中或伪造 Job 的反馈不纳入统计。
无真实供应商证据时不会以 Mock 结果补齐。试用时建议让甲方通过远程桌面操作这台
已准备好登录态的电脑，或由你共享屏幕并交出鼠标控制。不要直接把 8765 或 9222
暴露到公网；WebUI 当前没有登录鉴权，9222 还可读取专用浏览器的页面与登录态。

WebUI 能做：

- 一键完整研究：卖家精灵列表导出 → 汇总评分 → 高分 ASIN → 1688 找货 → 双报告交付。
- 运行前 preflight：检查 PPIO、Amazon cookies、1688 cookies、数据库、导出目录、1688 cooldown。
- 当 Amazon/1688 cookies 缺失时，主动显示登录态补充卡：先尝试从用户授权的
  9222 专用 Chrome 捕获站点 cookies；如尚未登录，则在该 Chrome 中打开登录页，
  用户完成扫码/验证码后点击“已登录，保存并检查”即可原子写入 `data/` 并刷新
  preflight。cookies 值不会返回浏览器前端。
- 启动 sourcing agent run：填写 category / marketplace / limit，默认 No-Mock 模式，避免正式结果混入 mock 供应商。
- 查看 Recent Runs：读取 `data/exports/candidates_*.json` / `.xlsx`。
- 查看和搜索历史候选商品：按 ASIN、标题、供应商搜索，并下载对应 Excel。
- 保存/取消保存候选商品：保存状态写入 `data/agent_saved_items.json`。
- Browser Assistant（可选）：在 Settings 中通过本地 `browser-use` 辅助检查 1688 登录态、诊断 Amazon/1688 页面、补采 1688 详情字段；不替换主 pipeline 爬虫。
- 查看每个 Run/ASIN 的执行节点、attempt 与状态；对 `human_required`、失败或已完成节点分别执行继续、重试或带原因的强制重跑。

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

Chrome 136+ 不再允许对默认用户目录启用 remote debugging，因此应启动一个专用、
非默认 profile。WebUI 的 Settings → Dedicated Chrome on port 9222 会检测连通性，
并提供 Windows/macOS/Linux 启动命令与一键复制。不要把 9222 暴露到公网或局域网；
Agent 能访问这个专用 profile 中的页面、cookies 和登录态。

系统会从 `${BU_CDP_HTTP}/json/version` 自动解析当前 `webSocketDebuggerUrl`，所以 Chrome 重启后通常不需要重新复制 `/devtools/browser/<id>`。`BU_CDP_WS=ws://.../devtools/browser/<id>` 仍可用于高级固定端点，但 browser id 可能随 Chrome 重启变化。

### SellerSprite 反查关键词浏览器导出（受控功能）

这项功能与上面的通用 Browser Assistant 相互独立：它只处理一个 Amazon **US**
ASIN 的 SellerSprite 可见反查关键词导出。浏览器能力默认**开启**，但导出仍会在
没有已审查的 SellerSprite locator profile 时被保护性拦截；仓库不会提供或猜测
该 profile。

启用前必须由已登录 SellerSprite 的用户在可见 Chrome 中亲自确认，并先完成真实
DOM、导出表头、扩展版本和 Windows 宿主机到 Docker 下载目录映射的脱敏记录。把
经过审查的 locator profile 保存在本机受控目录，不要提交 cookies、账号、密钥或
profile 内容到仓库。如需显式覆盖默认值：

```dotenv
SELLERSPRITE_BROWSER_ENABLED=true
```

在用户明确批准且上述记录完成后，可在正式 WebUI 的 SellerSprite 卡片中保存本机
配置。它会写入 Docker 数据卷中的
`data/sellersprite_browser_config.json`，因此容器重建不会丢失。这个文件只保留
容器内路径与“宿主机下载目录已确认”标记，不保留 Windows 绝对路径。环境变量仍可
作为非 UI 部署的覆盖项：

```dotenv
SELLERSPRITE_BROWSER_ENABLED=true
SELLERSPRITE_BROWSER_LOCATOR_PROFILE_PATH=/app/data/<your-reviewed-profile>.json
SELLERSPRITE_BROWSER_DOWNLOAD_DIR=/app/data/imports/sellersprite
SELLERSPRITE_BROWSER_HOST_DOWNLOAD_DIR=<your-separately-controlled-windows-directory>
BU_CDP_HTTP=http://host.docker.internal:9222
```

导出前，服务只在当前 CDP 附着的 Chrome 生命周期内调用
`Browser.setDownloadBehavior`，将文件写入项目控制的容器下载目录；不会修改 Chrome
首选项、注册表、cookie、账号或扩展权限。现场验证只允许在用户显式设置
`SELLERSPRITE_E2E=1` 后运行；该变量是一次性用户批准，不是日常开关。遇到
`SELLERSPRITE_LOGIN_REQUIRED`、`SELLERSPRITE_PERMISSION_REQUIRED`、
`SELLERSPRITE_QUOTA_EXCEEDED` 或 `CAPTCHA` 时，这些都是终止状态：停止并在 Chrome
中处理，不能重试、绕过或伪造成功。

正式可恢复 pipeline 的 market 阶段优先使用已启用的 Chrome/CDP 插件，自动逐 ASIN
执行 Reverse ASIN 导出并将其作为关键词市场证据进入评分；保留的 SellerSprite API
密钥不参与正式运行。浏览器导出只映射主关键词、月搜索量、购买量/率及
对应商品数；ASIN 月销量、Top10 集中度、季节性和关键词难度等未提供字段保持
`NULL`。小批量独立采集也可运行：

```bash
python3 main.py seller-sprite-batch --asin B00Q7OAN50 --asin B01M16WBW1
```

1688 Open Platform 匹配默认关闭（`ENABLE_ALIBABA_OPEN_API_MATCHER=false`）；即使
本地仍保留旧凭据，正式匹配也会直接使用浏览器路径，不先发送失败的 API 请求。

当前本机已验证登录、验证码和导出链路；“权限不足”与“配额耗尽”定位器采用
**首次自然出现时补录**的策略。不得为了采集它们去消耗配额、改变订阅或诱发账号
限制。提示首次出现时保留页面并记录脱敏 DOM 证据，再将审查后的 selector 写入本机
locator profile；在此之前，系统只保留相应的人机交接码，不声称该 selector 已验证。

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

环境变量：按 [部署说明](docs/DEPLOYMENT.md) 手工创建仅供本机使用、不得提交的 `.env`，至少需要 `PPIO_API_KEY`（视觉识别）。Amazon/1688 爬虫需要 cookies——在宿主机跑 `setup_amazon_login.py` / `setup_1688_login.py` 生成后放入 `data/`，容器通过卷挂载读取。关键变量：`PPIO_API_KEY`（视觉识别，必需）、`KEEPA_API_KEY`/`RAINFOREST_API_KEY`（Amazon API 抓取，可选，否则走 scrapling）、`MJJL_API_KEY`（卖家精灵市场分析，可选）、`ALIBABA_DETAIL_ENRICH_LIMIT=2`（每个商品最多补全的 1688 详情候选数）、`LOG_DIR=data/logs`（日志目录）、`ALIBABA_ALLOW_MOCK_SUPPLIERS=false`（正式跑保持 `false`）。

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

**阶段失败策略**：各阶段按持久化屏障推进。临时错误进入有上限的 `retry_wait`，登录、
验证码或权限问题进入 `human_required`，确定性失败保留为可审计终态；未知业务证据保持
缺失值，不会被伪装成零值或成功结果。

### ASIN 级恢复语义

SQLite 的 `execution_nodes` 是执行状态事实来源，`execution_attempts` 保存每次尝试，
`execution_operations` 审计继续/重试/强制重跑/取消操作。节点使用输入指纹、租约、
heartbeat 和 fencing token：输入未变的成功节点会直接复用，失效 worker 不能写回。
例如 A/B/C 中只有 B 的 match 失败，恢复时 A、C 不重跑；B 成功后仅继续 B 的下游，
再因聚合输入变化重跑 filter/export。业务快照通过 `result_key` 幂等提交；导出文件集
通过 `artifact_manifests`、SHA-256 和原子 rename 发布，残缺文件集不会显示为成功。

WebUI 自动从 SQLite 恢复中断节点，并展示 `retry_wait`、`human_required`、
`timed_out`、`skipped` 等状态。CLI 可显式执行：

```bash
python main.py resume-run --run-id <run_id>
```

本地 API 提供 `/api/runs/{run_id}/nodes` 和
`/api/runs/{run_id}/nodes/{node_id}/attempts`；节点操作必须携带当前
`resume_token`，过期页面不能覆盖较新的恢复操作。

详细状态机、故障模型和验收矩阵见 `execution/` 模块实现。

## 目录结构

```
amazon_selector/
├── main.py                 # CLI 入口（init-db | run | resume-run）
├── config/                 # settings.py(pydantic) + profit_params.yaml + scoring_weights.yaml
├── crawlers/               # Amazon BSR 采集（_amazon_extractors 共享选器 + scrapling/playwright 后端）
├── matchers/               # 1688 货源匹配（vision + playwright 爬虫 + verifier）
├── analyzers/              # profit_model / scorer / maijiajingling(卖家精灵)
├── pipeline/               # orchestrator(7阶段编排) + filters(排名)
├── reports/                # exporter(Excel/Markdown/JSON)
├── db/                     # SQLAlchemy 业务表、执行状态表、迁移与 session
├── execution/              # 节点状态机、租约、重试、幂等提交与 artifact 对账
├── tests/                  # pytest 自动化回归
├── data/                   # 缓存、cookies、导出文件、SQLite（.gitignore，不入库）
├── docs/                   # PRD / database_schema / scoring_spec / 选品参考
├── STATUS.md               # 当前状态 + 已知问题 + 下一轮计划
└── CHANGELOG.md            # 变更日志（Keep a Changelog）
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

- [STATUS.md](STATUS.md) — 当前状态、已知问题、下一轮计划
- [CHANGELOG.md](CHANGELOG.md) — 版本变更日志
- [docs/PRD.md](docs/PRD.md) — 产品需求文档
- [docs/scoring_spec.md](docs/scoring_spec.md) — 评分维度公式与示例
- [docs/database_schema.md](docs/database_schema.md) — 数据库表设计
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — 部署指南
