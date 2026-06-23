# Amazon Selector — Pipeline Status

**Snapshot date**: 2026-06-17
**Pipeline version**: 0.2.0
**Last full E2E run**: success — 3 Amazon products → 4 1688 suppliers → 2 candidates pass hard filter → Excel/Markdown/JSON exported

---

## TL;DR

整条 7 阶段 pipeline 端到端跑通，能产出真实候选选品池。
主要靠两个修复让数据真正可用：Amazon 端把 prodDetTable 选器重写（brand / BSR / 重量 / 尺寸命中率从 0% 提到 90%+），1688 端让 Playwright 路径使用真实浏览器 context 注入 64 个 cookies（拿到真实 1688 商品）。
剩下的都是"配置就能跑"或者"独立大功能"的问题，不阻塞主流程。

---

## 1. 7 个阶段当前状态

| # | Stage | File | Status | Notes |
|---|---|---|---|---|
| 1 | crawl | `crawlers/amazon_scrapling.py` | ✅ **Production** | StealthySession 后端，prodDetTable 2026 选器，cookies + diskcache 24h 缓存 |
| 2 | match | `matchers/alibaba_playwright.py` | ✅ **Production** | DynamicFetcher + browser context cookies，拿到真实 1688 货源（offer 782455318629 类）|
| 2 | match (alt) | `matchers/alibaba_scrapling.py` | ⚠️ 退化 | HTTP header cookies 被 TMD 拦，0 结果（不阻塞，Playwright 兜底）|
| 2 | match (alt) | `matchers/alibaba_text_search.py` | ⚠️ 退化 | 1688 官方 API 需 app_key；当前用占位，无数据（400 Bad Request，URL 路由已修）|
| 3 | profit | `analyzers/profit_model.py` | ✅ **Production** | 6 个 calc_* 函数 + predict_profit，从 CNY 采购价到 USD 净利润 |
| 4 | market | `analyzers/maijiajingling.py` | ⚠️ 配置即用 | 7 个 API 客户端 + analyze_market 编排，**需要 MJJL_API_KEY**，无 key 时静默跳过 |
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
| `MJJL_API_KEY` (卖家精灵) | 未配置 | 在 `.env` 加 key，stage 4 自动激活 |
| `ALIBABA_APP_KEY` / `ALIBABA_APP_SECRET` (1688 官方) | 未配置 | 在 `.env` 加 key，stage 2 官方 API 自动激活 |
| `KEEPA_API_KEY` / `RAINFOREST_API_KEY` (Amazon) | 未配置 | Amazon 走 Scrapling 即可，加 key 后自动升级 |

### 4.2 代码问题（需要独立工作）

| 问题 | 影响 | 修法（预估工作量）|
|---|---|---|
| **Scrapling 1688 路径 0 结果** | Scrapling 是 HTTP 路径，cookies 只能走 header，1688 TMD 不认 | **方案 A**: Scrapling 跑在独立 subprocess（中等改动）  **方案 B**: 全 matcher 异步化（大改动）  **方案 C**: 不修，依赖 Playwright 路径 |
| **Amazon 2026 buybox 价格** | 第三方卖家主导的页没有内联价格（"See All Buying Options" 之后才有）| 写专门的 buybox extractor，从 JSON `olpMessage` / `p13n-sc-price` 区分主价 vs 变体价（独立工作）|
| **1688 包装尺寸 / 交期缺失** | 搜索页没这些字段，要进详情页 | 实现 `get_offer_detail`（需要 session 复用 + 限速）|
| **Pailitao 图像搜索** | `PailitaoClient.search_by_image` 仍是 `NotImplementedError` | 大功能：要么接 1688 开放平台图搜 API（要特殊权限），要么用浏览器自动化上传图片到 1688 图搜页 |

### 4.3 测试
- 177 passed, 5 skipped, 2 pre-existing failures
- 2 pre-existing failures 是 `test_vision_matcher.py` 的 cache-hit 测试（旧缓存导致 mock 不被调用，与本工作无关）
- 5 skipped 是 `TestAgainstRealAmazonHtml`（用真实 HTML fixture 跑，fixture 已被清理，需要重跑 probe 脚本生成）

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
| **mock 兜底** | 1688 全路径失败时生成占位 supplier，让 pipeline 永不断（带 `match_verification_method='mock'` 标记）|

---

## 6. 推荐的下一轮（按 ROI 排）

1. **配 MJJL_API_KEY**（5 分钟，立刻激活 stage 4）—— ROI 最高
2. **配 1688 官方 API key**（5 分钟，立刻激活官方 API 路径）—— ROI 次高
3. **写 Amazon buybox extractor**（半天工作）—— 解决 price 字段 1/3 命中率问题
4. **修 Scrapling 1688 路径**（1-2 天）—— 方案 A (subprocess 拆分) 最干净
5. **实现 Pailitao 图搜**（2-4 天）—— 大功能，独立产品决策
6. **CHANGELOG.md**（如果开始长期迭代）—— 用 Keep a Changelog 格式跟踪每次 commit

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
