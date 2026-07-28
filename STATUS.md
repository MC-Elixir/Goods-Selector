# Amazon Selector — Pipeline Status

**Snapshot date**: 2026-07-20
**Pipeline mode**: deterministic 7-stage compatibility mode（Phase 3 `--mode agent` 尚未实现）

**Target-category sourcing**: Outdoor Storage、Patio Heater、Patio Furniture Sets、
Patio Umbrellas & Shade 已接入正式 `match_suppliers` 和可恢复 pipeline。目标产品执行 12 类
确定性去品牌查询、Amazon/1688 参数归一化、最多 10 个详情补全，并对品类、整品/配件、
子型、关键数值、材质和厂家身份执行硬门禁。只有 `keep` 进入利润/市场评分；拒绝与复核
证据写入 SQLite 和三种导出。合同与验收见
`docs/target-category-sourcing-contract.md`。

**Target contract benchmark**: 20 个合成规格/厂家案例覆盖四个品类，当前 decision accuracy、
strict keep precision、hard reject recall 和 rejection reason accuracy 均为 100%。这不是线上
准确率；真实队列目前只有 3 个未人工标注的伞类历史案例，因此 live 指标保持 `NULL`。

**Recoverable execution**: 7 阶段业务入口保持兼容，但调用层现已具备 run/ASIN 节点、
attempt、输入指纹、租约与 fencing、自动退避恢复、人工继续、幂等业务结果和原子
artifact set。SQLite 是恢复事实来源；CLI 使用 `resume-run --run-id`，WebUI 可查看并
操作节点。

**Current verification**: 2026-07-17 的 run #58 generation 2 完成 3 个 Amazon 商品，
SellerSprite 浏览器导出 3/3、1688 实时搜索 3/3、mock=0。TERRO 结果全部为灭蚁/诱饵
类供应商，两个床品 ASIN 收敛为床品/床笠类；没有再出现锅铲、餐盒、垃圾桶跨品类结果。
最终候选为 0，原因是成本尺寸/物流证据与利润评分门禁，不是流水线失败。

**Pipeline version**: 0.3.0 recoverable compatibility mode
**Last controlled E2E run**: [run #58 generation 2] success — 3 Amazon products；
SellerSprite 浏览器导出 3/3，1688 实时搜索 3/3，真实供应商证据覆盖率 100%，mock=0。
导出文件：[candidates_run_58_g2.xlsx](data/exports/candidates_run_58_g2.xlsx)。

**Regression**: 2026-07-20 全量离线回归为 948 passed、6 skipped；四品类规格合同、
正式匹配、查询证据、厂家门槛、可恢复落库、评分硬门禁和三种导出均在全套中通过。
20 个合成合同案例全部通过，历史 6ft 伞与 85cm 候选被稳定识别为伞径硬冲突；该历史
案例尚未人工标注，所以不计入线上准确率。当前 WSL 没有可用的 Docker 命令，
`docker compose config` 与镜像内 WebUI 复验仍待 Docker Desktop WSL integration 恢复。

**0.2.2（2026-06-23）**：放弃 1688 官方 API、仅用爬虫 —— 清空 `.env` 三个 `ALIBABA_*` key（官方 API 自动跳过）；新增 `enable_scrapling_matcher` 开关默认禁用被 TMD 拦的 Scrapling 死路径，直接降级 Playwright。主路径现为 Playwright 单路（详见 §4.1/§4.2 与 `CHANGELOG.md`）。

**0.2.1（2026-06-23）**：Stage 4 评分体系补完 —— `analyze_market()` 接入关键词选品（API 10），并修正评分中"月销量 / 月搜索量"混用（详见 §4.4 与 `CHANGELOG.md`）。待 `MJJL_API_KEY` 到位即可端到端验证。

---

## TL;DR

整条 7 阶段 pipeline 端到端跑通，能产出真实候选选品池。
主要靠两个修复让数据真正可用：Amazon 端把 prodDetTable 选器重写（brand / BSR / 重量 / 尺寸命中率从 0% 提到 90%+），1688 端让 Playwright 路径使用真实浏览器 context 注入 64 个 cookies（拿到真实 1688 商品）。
当前主要阻塞是外部市场数据凭证和 1688 API/页面稳定性；关键证据缺失时正式模式
会失败关闭，因此这些问题会阻止强推荐，这是预期的数据可靠性行为。

**正式 no-mock 模式**：主路径使用真实搜索/详情来源；被登录、captcha 或 TMD
拦截时进入人工处理或数据不足，不降级为 mock 候选。

---

## 1. 7 个阶段当前状态

| # | Stage | File | Status | Notes |
|---|---|---|---|---|
| 1 | crawl | `crawlers/amazon_scrapling.py` | ✅ **Production** | StealthySession 后端，prodDetTable 2026 选器，cookies + diskcache 24h 缓存 |
| 2 | match | `matchers/alibaba_playwright.py` | ✅ **Production** | DynamicFetcher + browser context cookies，拿到真实 1688 货源（offer 782455318629 类）|
| 2 | match (alt) | `matchers/alibaba_scrapling.py` | ⚠️ 退化 | HTTP header cookies 被 TMD 拦，0 结果（不阻塞，Playwright 兜底）|
| 2 | match (legacy) | `matchers/alibaba_text_search.py` | ⏸️ **Disabled** | 1688 Open API 仅保留诊断兼容；正式匹配默认不调用 |
| 3 | profit | `analyzers/profit_model.py` | ✅ **Production** | 6 个 calc_* 函数 + predict_profit，从 CNY 采购价到 USD 净利润 |
| 4 | market | `agent/sellersprite_service.py` | ✅ **Production** | 已登录 Chrome/CDP 插件逐 ASIN 导出 Reverse ASIN；保留的 API 密钥不参与正式运行 |
| 5 | score | `analyzers/scorer.py` | ✅ **Production** | 6 维度 score_* 纯函数 + score_product + apply_hard_filters；`test_weights_sum_to_one` 强制权重和 = 1.0 |
| 6 | filter | `pipeline/filters.py` | ✅ **Production** | rank_candidates 按 total_score + net_profit 排序 |
| 7 | report | `reports/exporter.py` | ✅ **Production** | Excel (openpyxl) + Markdown (jinja2) + JSON 三种格式 |

---

## 2. 实测数据（最近一次 E2E）

```
输入:    python main.py run --category "Home & Kitchen" --limit 3

Stage 1:  3 个 Amazon 产品 (TERRO 蚂蚁药 / Zevo 飞虫诱捕器 / CGK 床单)
Stage 2:  4 个 1688 供应商（含 1 个 LLM 视觉验证通过的真实 offer）
Stage 3:  例：B0CKY689WQ @ $24.99 → 净利率 33.9% / 净利润 $8.47
Stage 4:  MJJL 未配置 → 跳过
Stage 5:  B00E4GACB8=47.7  B0CKY689WQ=60.3  B01M16WBW1=58.8
Stage 6:  2 个通过硬性筛选
Stage 7:  data/exports/candidates_20260616_105525.{xlsx,json}
         data/exports/reports/B0*.md (每候选一份 Markdown 报告)
DB:       RunLog id=2 落库
```

---

## 3. 这一轮做了什么（按时间顺序）

### 3.1 Amazon 端基础设施
- `crawlers/_amazon_page.py` (新) — `PageLike` 协议 + `ScraplingPage` / `PlaywrightPage` 适配器，让一个 extractor 能在两个浏览器后端通用
- `crawlers/_amazon_extractors.py` (新) — 15 个共享提取函数，主路径走 **prodDetTable**（"Brand Name" / "Best Sellers Rank" / "Item Weight" / "Package Dimensions"），老选择器作 fallback
- `crawlers/amazon_scrapling.py` (重写) — 选 StealthySession（patchright 修补 chromium + curl_cffi 抗检测），删了所有重复的 `_extract_*` 函数
- `crawlers/amazon_playwright.py` (重写) — 同样调共享 extractors，0 重复代码

**效果对比**（同一 Amazon BSR Top 3 详情页）：

| 字段 | 旧版 | 新版 |
|---|---|---|
| brand | 1/3 | **3/3** |
| BSR | 0/3 | **3/3** |
| weight | 0/3 | **2/3** |
| price | 1/3 | 2/3（**已知遗留**：2026 第三方卖家主导页 buybox 提取）|

### 3.2 持久化层
- `crawlers/_amazon_cookies.py` (新) — `data/amazon_cookies.json` 原子读写（temp + `os.replace`）
- `crawlers/_amazon_cache.py` (新) — `diskcache` 24h TTL；keys `detail:US:B0ABC` / `bsr:US:home-garden:1`；captcha 时 `delete(key)` 避免污染
- `setup_amazon_login.py` (新) — headed 浏览器 + flag 文件交互登录（镜像 1688 的 setup）

**实测**：冷启 82.5s → 热缓存 7.0s（**11.8× 加速**），数据 100% 一致。

### 3.3 1688 端修复
- `matchers/alibaba_text_search.py:115` — URL 拼接 bug 修复（`f"{gw}{method}/"` → `f"{gw}/{method}/"`，少一个斜杠导致 100% 404，现在 400 是预期）
- `matchers/alibaba_playwright.py:137/174` — `proxy=self._proxy or ""` → `_playwright_proxy()` helper（空字符串让 Playwright 崩；改成 None 时不传）
- `matchers/__init__.py` — 加 "1688 需要登录 cookies" 提示到 docstring
- `setup_1688_login.py` — 多次重写：
  - 旧 `playwright.sync_api` → 换 `StealthySession`（patchright 抗检测）
  - 旧 `playwright_stealth` fallback → 删
  - URL 从 `login.1688.com/mini_login.htm`（404）→ `login.1688.com/member/signin.htm`（302 链到 `login.taobao.com/?...&from=1688web` —— 关键的 1688 登录入口）
  - polling loop 不再查 `session.context.pages`（StealthySession page-pool 不可靠），改纯 flag 文件 + 5s 心跳
  - 加 `data/.1688_save_flag`（`.amazon_save_flag` 的姊妹，避免名字冲突）

**用户症状（"闪退"）的真相**：脚本从来没闪退过——64 个 cookies 在每次运行中**成功保存**。用户看到"prompt 回来了"是因为脚本**保存完成正常退出**（2 秒一次 Enter 触发的误解是因为 cookies 已经被保存，登录态就绪了）。

### 3.4 共享代码重构
- `crawlers/_amazon_page.py` 适配器模式 — Scrapling 和 Playwright 后端共用一份解析逻辑
- `crawlers/_amazon_extractors.py` 纯函数 — 全部独立于浏览器，便于单测

---

## 4. 已知问题（不影响主流程）

### 4.1 配置问题（配 key 立刻能跑）

| API | 状态 | 修法 |
|---|---|---|
| `MJJL_API_KEY` (卖家精灵) | 未配置（已定订阅计划，见 §4.4）| 申请 4 接口试用 → 拿 key → 写 `.env` → stage 4 自动激活 |
| `ALIBABA_APP_KEY` / `ALIBABA_APP_SECRET` / `ALIBABA_ACCESS_TOKEN` (1688 官方) | **已弃用**（0.2.2 清空，仅走爬虫）| 如恢复官方 API：填回 `.env` 三个 key 即自动启用；此前明文 key 务必先到开放平台重置 |
| `KEEPA_API_KEY` / `RAINFOREST_API_KEY` (Amazon) | 未配置 | Amazon 走 Scrapling 即可，加 key 后自动升级 |

### 4.2 代码问题（需要独立工作）

| 问题 | 影响 | 修法（预估工作量）|
|---|---|---|
| **Scrapling 1688 路径 0 结果** | Scrapling 是 HTTP 路径，cookies 只能走 header，1688 TMD 不认 | **0.2.2 已采纳方案 C**：`settings.enable_scrapling_matcher` 默认 False，默认不跑、直接降级 Playwright；待修好后置 True 即可恢复（无需改代码） |
| **Amazon 2026 buybox 价格** | 第三方卖家主导的页没有内联价格（"See All Buying Options" 之后才有）| 写专门的 buybox extractor，从 JSON `olpMessage` / `p13n-sc-price` 区分主价 vs 变体价（独立工作）|
| **1688 详情字段覆盖不稳定** | 详情抓取已接通，但不同模板、登录拦截或字段缺省仍可能导致包装尺寸、交期、厂家身份缺失 | 保持 `manual_review/retry`，用真实标注队列逐字段补选择器，不以搜索卡片值替代详情证据 |
| **Pailitao 图像搜索** | `PailitaoClient.search_by_image` 仍是 `NotImplementedError` | 大功能：要么接 1688 开放平台图搜 API（要特殊权限），要么用浏览器自动化上传图片到 1688 图搜页 |

### 4.3 测试
- **当前（2026-07-20）**：全量离线回归 948 passed、6 skipped；四品类合成合同 20/20，真实队列 3 条均未标注，live accuracy 为 `NULL`
- **0.2.1 实测（2026-06-23）**：181 passed, 5 skipped, 2 pre-existing failures —— 较 0.2.0 新增 4 个用例（`test_maijiajingling.py`）并扩展 `test_scoring.py`，无回归
- 2 pre-existing failures 仍是 `test_vision_matcher.py` 的 cache-hit 测试（旧缓存导致 mock 不被调用，与本工作无关）
- 5 skipped 仍是 `TestAgainstRealAmazonHtml`（真实 HTML fixture 待重跑 probe 脚本生成）

### 4.4 卖家精灵 API 订阅计划（2026-06-23 决策）

**订阅策略（先试用，别乱点）**：卖家精灵每个服务都有"试用"，但**每个服务仅可提交一次试用申请**。先只申请下面 4 个接口的试用（对应 `analyze_market()` 编排的 4 步）：

| 接口 | 名称 | 在 analyze_market 中的作用 |
|---|---|---|
| 3 | ASIN 详情 | 入口：基础信息 + BSR + 类目（API 26 依赖其 categoryId） |
| 26 | BSR 销量预测 | 日/月销量估计 → `est_monthly_sales` → demand 维度 + 硬筛 |
| 1 | 查竞品 | 竞品集中度 + 头部份额 → competition 维度 |
| 10 | 关键词选品 | 搜索量 + 机会指数 → demand 维度（**0.2.1 新接入**） |

价格见卖家精灵开放平台 **API 价格页**（按接口计费）。

**低成本备选**：仅做 MVP 小批量人工验证时，官方 **MCP Basic**（月付 ¥99、1000 次/月）可作为人工核验工具；但要接入现有代码的 Stage 4，仍以 API 为直接路径（MCP 价格见卖家精灵 **MCP 价格页**）。

**拿到 key 后**：写 `.env` 的 `MJJL_API_KEY=` → `python -c "from analyzers.maijiajingling import MaijiajinglingClient; print(MaijiajinglingClient().get_visits())"` 验额度 → `python main.py run --category "Home & Kitchen" --limit 3` 端到端，确认 `market_analyses` 表有数据、demand/competition 维度真正进分。

**0.2.1 代码已就位**（无需等 key 即已写入，待 key 到位自动激活）：
- `analyzers/maijiajingling.py` — `analyze_market()` 第 4 步接 `keyword_research()`，新增 `_extract_keyword_metrics()` 归一化 `searchVolume` / `monthlySearches` / `keywordDifficulty` / `opportunityScore` 等字段名，无显式机会指数时用搜索量+购买率+竞争度保守估算
- `analyzers/scorer.py` — `score_demand()` 的 `monthly_sales` 改用 `est_monthly_sales`（真实/预估销量），`search_volume_monthly` 单独传入；`apply_hard_filters()` 的 `monthly_sales` 同步改为只看销量——修正此前"月销量 vs 月搜索量混用"导致硬筛语义不准的问题
- `pipeline/orchestrator.py` — `MaijiajinglingClient` 改 `with` 上下文管理，自动关连接

---

## 5. 架构决策记录

| 决策 | 理由 |
|---|---|
| **Scrapling 作为 Amazon 默认 backend** | 抗检测更强（patchright）、TLS 指纹伪装、cold start 慢但热缓存 11.8× 加速 |
| **Playwright 作为 1688 默认 backend** | 1688 强制 JS 渲染，HTTP 路径被 TMD 拦，只有真浏览器 context 能注入 HttpOnly cookies |
| **prodDetTable 替代老 bullet 列表选择器** | 2026 Amazon 详情页唯一可靠的字段源（"Brand Name" / "Item Weight" / "Best Sellers Rank" / "Package Dimensions"）|
| **`PageLike` 适配器模式** | 一个 extractor 能在 Scrapling / Playwright 两个后端共用，避免选器逻辑漂移 |
| **Snapshot 模式 (ProfitSnapshot / Score)** | 利润参数 / 评分权重变化后，历史决策可回放；`params_snapshot` JSON 字段记录当时的 YAML |
| **diskcache 24h TTL** | 同 ASIN / BSR 列表页回放时秒出；captcha 命中时 `delete(key)` 避免脏数据 |
| **MJJL fallback 设计** | 卖家精灵无 key 时静默跳过而不是 crash，让 pipeline 仍能产出候选（少一个维度）|
| **硬性筛选在 yaml 配置** | 净利率 / 总分 / 月销 / MOQ / 品牌黑名单 阈值都在 `scoring_weights.yaml`，改配置不动代码 |
| **正式 no-mock** | 正式 WebUI/四品类路径禁用 mock；1688 全路径失败时记录数据不足或人工处理，不把占位 supplier 送入结果。mock 仅保留给显式开启的测试/调试兼容路径 |
| **仅走爬虫（0.2.2）** | 放弃未验证可用的 1688 官方 API，默认禁用被 TMD 拦截的 Scrapling HTTP 路径；Playwright 注入 cookies 获取真实 offer。旧版调试 mock 仍可显式开启，但当前正式 no-mock 路径失败关闭 |

---

## 6. 推荐的下一轮（只按匹配质量排序）

1. **建立真实人工金标**：四个品类各复核至少 30 个 Amazon 商品，每个商品标记正确 1688 厂家、明确无匹配或需要复核；禁止把合成合同结果当线上准确率。
2. **逐品类受控实跑**：Docker 环境恢复后，每类先跑 10 个 Amazon US 商品，保存 12 类查询、原始候选、详情证据、严格决策与导出，人工逐条确认参数和厂家身份。
3. **按误差类型调规则**：分别统计错品类、整品/配件、子型、数值、材质、厂家误判和证据缺失；只根据已复核的 false positive/false negative 调整解析器、容差和查询词。
4. **扩充真实详情解析 fixture**：优先补容量/尺寸、燃料与 BTU/功率、家具件数与组件、伞径/GSM，以及厂家/贸易商字段的多模板页面样本。
5. **补多图视觉验收**：对文本参数无法确认的候选核验 Amazon 主辅图和 1688 SKU/详情图；视觉缺失继续进入复核，不生成固定相似度。
6. **达到上线门槛后再扩量**：每类真实 P@1 ≥ 90%、硬冲突召回 ≥ 95%、参数字段准确率 ≥ 95%，且错误样本均可追溯到证据后，再扩大自动搜索范围。

---

## 7. 关键文件速查

```
amazon_selector/
├── main.py                              # CLI 入口 (init-db | run)
├── CLAUDE.md                            # 给未来 Claude 的指南
├── DESIGN.md                            # 原始设计文档
├── STATUS.md                            # ← 你正在读的
├── requirements.txt
├── setup_amazon_login.py                # 一次性 Amazon 登录 → cookies
├── setup_1688_login.py                  # 一次性 1688 登录 → cookies
│
├── crawlers/
│   ├── _amazon_page.py                  # PageLike 协议 + Scrapling/Playwright 适配器
│   ├── _amazon_extractors.py            # 共享字段提取（prodDetTable 主路径）
│   ├── _amazon_cookies.py               # data/amazon_cookies.json 原子读写
│   ├── _amazon_cache.py                 # diskcache 24h TTL
│   ├── amazon_scrapling.py              # Amazon 默认 backend（生产）
│   ├── amazon_playwright.py             # Amazon 备用 backend
│   ├── amazon_bsr.py                    # 后端 dispatcher (auto→scrapling→keepa→...)
│   ├── amazon_keepa.py / amazon_rainforest.py  # API 后端（按 key 自动启用）
│
├── matchers/
│   ├── __init__.py                      # match_suppliers 编排（vision + 5 路径 + verifier + LLM）
│   ├── alibaba_playwright.py            # 1688 主路径（生产）
│   ├── alibaba_scrapling.py             # 1688 备用（HTTP，被 TMD 拦）
│   ├── alibaba_text_search.py           # 1688 官方 API（需 key）
│   ├── alibaba_pailitao.py              # 拍立淘图搜（NotImplementedError）
│   ├── vision_analyzer.py               # PPIO/Anthropic 视觉 → 中文关键词
│   ├── verifier.py                      # 启发式 + LLM 视觉验证
│
├── analyzers/
│   ├── profit_model.py                  # 利润预测（6 成本项 + 净利率）
│   ├── scorer.py                        # 6 维度评分 + 硬性筛选
│   ├── maijiajingling.py                # 卖家精灵（需 MJJL_API_KEY）
│
├── pipeline/
│   ├── orchestrator.py                  # 7 阶段编排
│   ├── filters.py                       # rank_candidates
│
├── reports/
│   ├── exporter.py                      # Excel + Markdown + JSON
│
├── config/
│   ├── settings.py                      # pydantic-settings（所有 API key / URL）
│   ├── profit_params.yaml               # 成本率
│   ├── scoring_weights.yaml             # 评分权重（必须和=1.0）
│
├── db/
│   ├── models.py                        # 6 个 ORM 表
│   ├── session.py                       # session_scope 上下文
│   ├── init_db.py                       # 建表入口
│
└── tests/
    ├── test_amazon_scrapling.py         # 46 个测试（共享 extractors）
    ├── test_amazon_cookies.py           # 12 个测试
    ├── test_amazon_cache.py             # 10 个测试
    ├── test_crawlers.py                 # dispatcher + 旧 fallback
    ├── test_profit_model.py
    ├── test_scoring.py
    ├── test_vision_matcher.py           # 2 个 pre-existing failure（与本工作无关）
```
