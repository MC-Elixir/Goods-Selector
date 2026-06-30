# Amazon Selector

Amazon Best Seller 选品自动化系统。给定一个 Amazon 类目 → 爬取 BSR 榜单产品 → 视觉识别 + 1688 爬虫匹配货源 → 利润预测 → 6 维度评分 → 硬性筛选 → 排名 → 导出候选选品池（Excel / Markdown / JSON）。

**当前版本 0.2.2**（2026-06-23）。7 阶段 pipeline 端到端跑通，测试 181 passed。详见 [STATUS.md](STATUS.md) / [CHANGELOG.md](CHANGELOG.md) / [SHOWCASE.md](SHOWCASE.md)。

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
python main.py run --category "Toys & Games" --limit 10 --marketplace UK

# 5. 跑测试（纯单元测试，不联网、不需 API key）
pytest tests/
```

## Agent WebUI

本项目现在提供一个本地 Agent 控制台，把"环境 + 工具 + 系统提示 + 循环"落到可操作界面：

```bash
python main.py agent-web
# 打开 http://127.0.0.1:8765
```

WebUI 能做：

- 运行前 preflight：检查 PPIO、Amazon cookies、1688 cookies、数据库、导出目录、1688 cooldown。
- 启动 sourcing agent run：填写 category / marketplace / limit，默认 No-Mock 模式，避免正式结果混入 mock 供应商。
- 查看 Recent Runs：读取 `data/exports/candidates_*.json` / `.xlsx`。
- 查看和搜索历史候选商品：按 ASIN、标题、供应商搜索，并下载对应 Excel。
- 保存/取消保存候选商品：保存状态写入 `data/agent_saved_items.json`。

## 一次性登录（首次使用必做）

Amazon 与 1688 都需要登录态 cookies 才能稳定爬取（否则被反爬弹到登录页）：

```bash
python setup_amazon_login.py     # 弹浏览器手动登录 Amazon → 存 data/amazon_cookies.json
python setup_1688_login.py       # 弹浏览器手动登录 1688  → 存 data/1688_cookies.json
```

cookies 会过期（通常数天~两周），过期后 1688 搜索会被 TMD 风控弹回登录页、货源匹配降级到 mock 占位。届时重跑对应登录脚本刷新即可。

## 7 阶段流水线

```
main.py run --category --limit --marketplace
  └─ pipeline/orchestrator.py::run_pipeline
       1. crawl    crawlers/amazon_bsr.py      Amazon BSR 榜单 → ProductDTO（Scrapling 抗检测后端，prodDetTable 选器）
       2. match    matchers/__init__.py        视觉识别→Playwright 1688 爬虫→mock 兜底→启发式+LLM 验证
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
├── matchers/               # 1688 货源匹配（vision + playwright 爬虫 + verifier + mock 兜底）
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
- **1688 仅走爬虫**（0.2.2）：弃用官方 API、默认禁用被 TMD 拦的 Scrapling HTTP 路径，主路径=Playwright 注入 cookies 拿真实 offer，mock 兜底保证永不断流。

## 文档

- [SHOWCASE.md](SHOWCASE.md) — 展示文档：系统介绍、架构图、测试结果、成果文件指引
- [STATUS.md](STATUS.md) — 当前状态、已知问题、下一轮计划
- [CHANGELOG.md](CHANGELOG.md) — 版本变更日志
- [docs/PRD.md](docs/PRD.md) — 产品需求文档
- [docs/scoring_spec.md](docs/scoring_spec.md) — 评分维度公式与示例
- [docs/database_schema.md](docs/database_schema.md) — 数据库表设计
