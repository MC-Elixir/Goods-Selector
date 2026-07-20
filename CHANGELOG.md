# Changelog

本文件记录 Amazon Selector pipeline 的变更，格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased] — 2026-07-17

### Added
- ASIN/run 级持久化执行节点、不可变 attempt、租约/heartbeat/fencing、重试退避、人工继续、取消与强制重跑审计。
- `resume_pipeline(run_id)`、`python main.py resume-run --run-id ...`，以及 WebUI 节点状态和带原因的恢复操作。
- 业务快照 `result_key` 幂等提交；导出 artifact set 使用 manifest、SHA-256、原子 rename 和崩溃对账。

### Changed
- 兼容的 7 阶段 `run_pipeline` 入口改由可恢复协调器执行，原业务采集、匹配、利润、市场、评分、筛选与导出函数继续复用。
- WebUI 重启时以 SQLite 为执行事实来源恢复原 `run_id`，不再把所有中断任务直接改成失败。
- 阶段屏障会等待 `pending`、`running` 和 `retry_wait` 节点；要求导出时，只有完整
  artifact set 已提交才能把 Run 汇总为成功。
- SellerSprite 市场数据门禁改为 Chrome/CDP 插件优先；失效但保留的 API 密钥不再阻塞正式运行。
- 1688 Open API 匹配默认关闭，正式路径直接使用浏览器搜索；遗留客户端仅保留显式诊断兼容。
- SellerSprite Reverse-ASIN 浏览器证据前置到 1688 匹配之前，并把最多 20 条脱敏关键词候选保存在市场证据中供搜索计划使用。
- SellerSprite v5 响应式布局适配：结果标记与导出控件分离等待，支持明确的溢出菜单和 portal 导出按钮；人工状态会立即停止后续 ASIN。
- 1688 查询新增供应链表达转换；数量/容量仅作为品类词修饰语，不再以 `12件套` 等规格词独立搜索。
- 匹配验证新增灭蚁、驱蚊、杀蟑、床品、餐厨和垃圾桶品类标准化与跨品类硬门禁；供应商销量只参与商业排序，不再冒充语义相关性。
- 标题 fallback 使用 ASCII 词边界，修复 `solid` 被误识别为 `lid` 的问题；PPIO 模型名校正为当前 key 可见的 `qwen/qwen3.5-plus`。

### Verified
- 3-ASIN 故障注入证明 A/C 成功节点不重复调用，B 恢复后只执行 B 与受影响的 filter/export。
- 真实 3-ASIN no-mock run #56 完成：SellerSprite 浏览器导出 3/3，审计样本市场数据与真实供应商证据覆盖率均为 100%。
- TERRO `B00E4GACB8` 回归证明高销量 `12件套` 锅铲厨具被拒绝，灭蚁饵剂候选保留；本轮相关 42 个测试通过。真实复跑因 9222 与 8765 均不可达而未执行。
- 真实 run #58 generation 2：3/3 SellerSprite 导出、3/3 1688 实时搜索、mock=0；TERRO 供应商全部为灭蚁/诱饵类，两个床品 ASIN 收敛为床品/床笠类，Excel/JSON 各 3 行。最终候选 0 是利润与物流证据门禁结果，不是运行失败。
- 适配器与语义专项回归 134 passed；PPIO 单图调用返回 `NOT_ENOUGH_BALANCE`，因此视觉分析按设计降级，未伪造视觉证据。
- 在真实 `data/amazon_selector.db` 副本上应用 `0004_recoverable_execution`：`integrity_check=ok`、无外键错误，原业务表行数保持一致。
- 全量回归为 890 passed、6 skipped、0 failed；真实 no-mock run #55 得到 2 条真实
  1688 货源、mock=0，三类 artifact manifest 全部 committed。SellerSprite 密钥无效
  导致市场证据缺失，Docker Desktop engine 未运行导致镜像内验证未执行，均按环境限制保留。

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
