# Changelog

本文件记录 Amazon Selector pipeline 的变更，格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [0.2.2] — 2026-06-23

放弃 1688 官方 API、仅用爬虫；并修复 Amazon 详情页爬取超时问题。

### Fixed
- `crawlers/amazon_scrapling.py` — Amazon 详情页爬取全程超时（默认等 `load` 事件被第三方资源拖到 60s × 3 次重试全失败）。改两处 `fetch`：① `disable_resources=True` 砍图片/字体/广告；② 超时 60s→25s；③ 详情页用 `wait_selector="#productTitle, #prodDetails, #detailBullets_feature_div"` 等关键元素而非整页 load，失败则回退重试。实测 5 个 ASIN 从全失败 → 32s 全部成功。

### Changed
- `.env` — 清空 `ALIBABA_APP_KEY` / `ALIBABA_APP_SECRET` / `ALIBABA_ACCESS_TOKEN`（官方 API 路径自动跳过）；此前明文 key 务必到开放平台重置。
- `config/settings.py` — 新增 `enable_scrapling_matcher: bool = False` 开关。
- `matchers/__init__.py` — Step 2b 守卫加上 `settings.enable_scrapling_matcher`，默认不跑被 TMD 拦的 Scrapling HTTP 路径、直接降级 Playwright；代码保留，置 True 即恢复。降级链 docstring 同步更新。

### 决策
1688 货源匹配仅走爬虫（Playwright 主路径 → mock 兜底）。理由：官方 API 从未验证可用（一直 400），且 Playwright 已能拿真实 offer；简化依赖、少一个付费 key。代价：采购价 / MOQ / 阶梯价 / 交期等结构化字段需靠详情页爬虫补（见 STATUS.md §4.2）。

### 验证
- `pytest tests/` → 181 passed, 5 skipped, 2 pre-existing failures（无回归）。
- `settings.enable_scrapling_matcher=False`、三个 `ALIBABA_*` key 均为空，确认官方 API 与 Scrapling 均跳过。

---

## [0.2.1] — 2026-06-23

Stage 4 评分体系补完：接入关键词选品数据 + 修正"月销量 / 月搜索量"混用。代码已就位，待 `MJJL_API_KEY` 到位即端到端激活。

### Added
- `analyze_market()` 新增第 4 步：调用关键词选品（API 10），将 `main_keyword` / `search_volume_monthly` / `keyword_difficulty` / `opportunity_score` / `seasonality` 填入 `MarketAnalysisDTO`。
- `analyzers/maijiajingling.py` 新增 `_extract_keyword_metrics()` —— 宽松归一化卖家精灵不同字段名（`searchVolume` / `monthlySearches` / `keywordDifficulty` / `opportunityScore` 等）；无显式机会指数时用「搜索量×0.45 + 购买率×0.30 + 竞争度×0.25」保守估算。
- 新增 `tests/test_maijiajingling.py`（4 个用例，覆盖 4 接口编排 + 关键词归一化）。

### Changed
- `analyzers/scorer.py::score_product()` —— `score_demand()` 的 `monthly_sales` 改用 `est_monthly_sales`（真实/预估销量，回退 `product.estimated_monthly_sales`），`search_volume_monthly` 作为独立输入传入。
- `apply_hard_filters()` 的 `monthly_sales` 同步改为只看销量，不再把搜索量当销量——修正此前硬筛语义不准（销量门槛被搜索量误触发 / 误绕过）。
- `pipeline/orchestrator.py` —— `MaijiajinglingClient` 改为 `with` 上下文管理，自动关闭 httpx 连接。
- 扩展 `tests/test_scoring.py`，覆盖销量与搜索量分离后的 demand 评分与硬筛。

### Docs
- `STATUS.md` 升级到 0.2.1，新增 §4.4「卖家精灵 API 订阅计划」。

### 验证
- `pytest tests/` → 181 passed, 5 skipped, 2 pre-existing failures（2 个 vision-matcher cache-hit 失败与本变更无关，0.2.0 起即存在）。

---

## [0.2.0] — 2026-06-17

7 阶段 pipeline 端到端跑通基线：Amazon 端 prodDetTable 选器重写（brand/BSR/重量命中率 0%→90%+），1688 端 Playwright 路径注入真实浏览器 cookies 拿到真实货源。详见 `STATUS.md`。
