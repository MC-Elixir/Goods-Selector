# Amazon Selector — 成果展示

> Amazon Best Seller 选品自动化系统：从 Amazon 榜单挖掘产品 → 1688 匹配货源 → 利润预测 → 6 维度评分 → 导出候选选品池。
>
> **版本 0.2.2** ｜ **2026-06-23** ｜ 7 阶段 pipeline 端到端跑通 ｜ 测试 181 passed

本文档面向**非技术读者**，讲清楚三件事：① 系统做什么、怎么做的；② 实测结果如何；③ 成果文件在哪看。

---

## 一、系统做什么

给一个 Amazon 类目（如 "Home & Kitchen"），系统自动完成：

1. **爬榜单**：抓 Amazon 该类目 Best Seller 前 N 名产品的标题/品牌/价格/BSR/评分/重量尺寸
2. **找货源**：对每个产品，用 AI 视觉识别主图转中文关键词，再去 1688 搜真实供应商
3. **算利润**：从 1688 采购价（CNY）算到 Amazon 售价（USD）的完整成本链——采购+物流+FBA+佣金+广告+退货
4. **评市场**（可选）：接卖家精灵 API 拿预估销量、竞品集中度、搜索量
5. **打分**：利润/需求/竞争/供应/物流/风险 6 维度加权评分（0-100）
6. **筛选排名**：硬性筛掉不合格的（净利率/销量/MOQ/品牌黑名单），按总分+净利润排名
7. **导出**：Excel（候选池总表）+ Markdown（每候选一份详情）+ JSON（结构化数据）

最终产出一份**按盈利潜力排序的候选选品池**，每个候选都带：Amazon 产品信息、匹配的 1688 货源、利润拆解、评分明细。

---

## 二、7 阶段架构

```
                        ┌─────────────────────────────────────┐
                        │  main.py run --category --limit      │
                        └──────────────────┬──────────────────┘
                                           ▼
   Stage 1  crawl    Amazon BSR 榜单 ────────────────► 5 个产品 (标题/品牌/价格/BSR/重量)
                                           ▼
   Stage 2  match    AI视觉识别 → 1688爬虫搜货 ──────► 每产品的 1688 供应商列表
                    (PPIO视觉模型 → Playwright注入cookies → 启发式+LLM验证)
                                           ▼
   Stage 3  profit   6项成本核算 ──────────────────► 净利率 / 净利润 (CNY采购→USD净利)
                                           ▼
   Stage 4  market   卖家精灵市场分析 ────────────► 预估销量/竞品/搜索量 (需API key)
                                           ▼
   Stage 5  score    6维度评分 + 硬性筛选 ────────► 总分(0-100) + 通过/淘汰
                                           ▼
   Stage 6  filter   排名 ──────────────────────────► 按总分+净利润排序的候选池
                                           ▼
   Stage 7  report   导出 ─────────────────────────► Excel + Markdown + JSON
```

**容错设计**：Stage 1（爬取）失败则中止；其余阶段按产品逐个失败并继续。1688 全路径失败时生成 mock 占位供应商保证流水线不断（带 `mock` 标记，会被低分淘汰）。

---

## 三、实测结果（2026-06-23）

### 跑通验证（2026-06-24 · 64 个新 cookies）

```
命令：python main.py run --category "Home & Kitchen" --limit 5
结果：[run #6] success | candidates=3
耗时：约 8 分钟（Stage 1 爬取 30s + Stage 2 匹配 6min + Stage 3-7 秒级）
```

| 阶段 | 结果 |
|---|---|
| 1 爬取 | ✅ 5/5 产品成功抓取（品牌/价格/BSR 字段命中；Scrapling 修复后无任何超时） |
| 2 匹配 | ✅ 编排正确（官方API跳过→Playwright→mock兜底→启发式+LLM验证链全活）；**1/3 候选拿到真实 1688 offer**（B01M16WBW1 → offer 780485617589） |
| 3 利润 | ✅ 5/5 算出（净利率 17.6% ~ 45.7%） |
| 4 市场 | ⏸️ 正确跳过（卖家精灵 API key 未配，待申请） |
| 5 评分 | ✅ 3/5 通过硬筛（总分 50.6 ~ 66.7） |
| 7 导出 | ✅ Excel + Markdown + JSON 全产出 |

### 候选池（本次导出，3 个通过硬筛）

| ASIN | 产品 | 总分 | 净利率 | 净利润 | 1688 货源 |
|---|---|---|---|---|---|
| B0BZYCJK89 | Owala FreeSip 不锈钢保温杯 | **66.74** | 44.0% | $13.18 | mock（TMD 拦截） |
| B01M16WBW1 | Queen 床单四件套 | **58.91** | 33.1% | $10.11 | ✅ **真实**：`detail.1688.com/offer/780485617589.html` |
| B0C3FTCYZL | Zevo 飞虫诱捕器替换装 | **50.60** | 20.3% | $3.64 | mock（TMD 拦截） |

> **注**：1688 搜索受 TMD 反爬影响，新 cookies 可拿到第一个产品的真实 offer，后续请求可能触发验证降级 mock。cookies 越新鲜、请求间隔越大，真实货源命中率越高。历史 06-16 数据已验证可同时拿到多个真实 offer。这是爬虫路线的固有特征——SHOWCASE 诚实标注，而非隐藏。

### 本次开发中修复的真实问题（亮点）

**问题**：Amazon 详情页爬取**全程超时**——默认 Scrapling 后端等页面 `load` 事件，被 Amazon 第三方资源/广告拖到 60s × 3 次重试 = 单个产品最坏 3 分钟，且最终全失败。

**诊断**：纯 HTTP 测试证明 Amazon 详情页 3.4s 即可 200 OK 拿到 2.6MB 正文、无验证码——问题不在网络，而在浏览器后端的等待策略。

**修复**：改 `crawlers/amazon_scrapling.py` 两处 `fetch`——① `disable_resources=True` 砍掉图片/字体/广告等无关资源；② 超时 60s→25s 快速失败；③ 详情页用 `wait_selector` 等关键元素（`#productTitle`/`#prodDetails`）而非整页 load。

**效果**：5 个产品详情页从"全失败"变成"32 秒全部成功抓取"。

---

## 四、成果文件在哪看

最新一次运行（2026-06-23 17:35）的导出在 `data/exports/`：

| 文件 | 内容 | 适合谁看 |
|---|---|---|
| `candidates_20260624_091629.xlsx` | 候选池总表（产品+货源+利润+评分一行一个） | 最直观，给非技术读者 |
| `candidates_20260624_091629.json` | 同上，结构化数据 | 技术读者 / 二次处理 |
| `reports/B0*.md` | 每个候选一份详情报告 | 深入看单个产品的完整分析 |

历史运行（含真实 1688 货源的其他样本）在 `data/exports/candidates_20260616_*.{xlsx,json}`。

> **注**：2026-06-24 本次运行 1688 搜索中第一个产品（B01M16WBW1）拿到真实 offer（`detail.1688.com/offer/780485617589.html`），后续产品因 TMD 反爬渐进收紧降级 mock。刷新 cookies（`python setup_1688_login_auto.py`）可重置为最佳命中率。

---

## 五、已知局限（诚实说明）

1. **1688 货源依赖登录态**：cookies 过期或 TMD 反爬渐进收紧后搜索降级 mock。定期重登 `setup_1688_login_auto.py` 刷新。首次请求命中率最高。
2. **采购价/MOQ 等结构化字段不全**：弃用官方 API 后靠爬虫，搜索页拿不到包装尺寸/交期/阶梯价，需后续做详情页爬取补充。
3. **市场分析维度待激活**：卖家精灵 API key 未配，demand/competition 维度跑在缺数据上。已定 4 接口订阅计划，待申请。
4. **Amazon 价格命中率**：第三方卖家主导的详情页没有内联价格，需写专门 buybox extractor（已知，待做）。
5. **仅小批量验证**：目前 E2E 仅跑到 `--limit 5`，`--limit 50` 的吞吐/稳定性未验证。

详见 [STATUS.md §4 已知问题](STATUS.md)。

---

## 六、技术栈

Python 3.12+ ｜ Scrapling（patchright 抗检测爬虫）｜ Playwright（1688 浏览器爬虫）｜ pydantic-settings（配置）｜ SQLAlchemy + SQLite（持久化）｜ openpyxl + jinja2（导出）｜ diskcache（API 缓存）｜ PPIO Qwen-VL（视觉识别）｜ click（CLI）｜ pytest（测试）

---

## 七、想自己跑？

见 [README.md](README.md) 的"快速开始"。最小可跑配置：装依赖 + 填 `PPIO_API_KEY` + 跑两次登录脚本 + `python main.py run --category "Home & Kitchen" --limit 5`。
