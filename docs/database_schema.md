# 数据库 Schema 设计

## 设计原则

1. **快照而非覆盖**：`profit_snapshots` 和 `scores` 都不修改历史记录，每次跑流水线都新增。便于参数调整后做对比和回归。
2. **参数可追溯**：`params_snapshot` / `weights_snapshot` 字段把当时的 YAML 配置存成 JSON，决策可复现。
3. **保留原始数据**：每个外部 API 的返回都存到 `raw_data` 字段，便于事后字段挖掘。
4. **时间统一 UTC**：所有时间字段 UTC 存储，展示时再转本地时区。

---

## 实体关系图

```
products (1) ──┬── (n) suppliers
               ├── (n) profit_snapshots ──► supplier
               ├── (n) scores
               └── (n) market_analyses

run_logs (独立)
```

---

## 表清单

### `products` — Amazon 产品主表

唯一性：`(asin, marketplace)`

关键字段：


| 字段                                                   | 类型             | 说明                |
| ---------------------------------------------------- | -------------- | ----------------- |
| `asin`                                               | VARCHAR(20)    | Amazon 产品 ID      |
| `marketplace`                                        | VARCHAR(8)     | US / UK / DE / JP |
| `category` / `subcategory`                           | VARCHAR(120)   | 类目                |
| `title` / `brand`                                    | TEXT / VARCHAR | 标题与品牌             |
| `price` / `bsr_rank` / `rating` / `review_count`     | NUM            | 核心销售指标            |
| `review_velocity_30d`                                | INTEGER        | 30 天评论增速，反映热度     |
| `weight_kg` / `length_cm` / `width_cm` / `height_cm` | REAL           | 物理尺寸（影响 FBA 和头程）  |
| `raw_data`                                           | JSON           | Keepa 原始返回        |


索引：`asin`、`category`、`brand`、`bsr_rank`、复合 `(category, bsr_rank)`。

---

### `suppliers` — 1688 货源

外键：`product_id → products.id`，唯一性 `(product_id, alibaba_offer_id)`。

关键字段：


| 字段                  | 类型          | 说明                                                  |
| ------------------- | ----------- | --------------------------------------------------- |
| `alibaba_offer_id`  | VARCHAR(40) | 1688 商品 ID                                          |
| `image_similarity`  | REAL        | 拍立淘返回的图片相似度（0-1）                                    |
| `text_similarity`   | REAL        | 标题文本相似度（如有）                                         |
| `moq`               | INTEGER     | 起订量                                                 |
| `price_tiers`       | JSON        | `[{qty: 50, price: 12.5}, {qty: 200, price: 10.8}]` |
| `base_price_cny`    | REAL        | 阶梯价中位（CNY），方便排序                                     |
| `monthly_sales`     | INTEGER     | 月销量                                                 |
| `repeat_buyer_rate` | REAL        | 回头率（0-1）                                            |
| `is_factory`        | BOOLEAN     | 是否实力商家 / 工厂                                         |


---

### `profit_snapshots` — 利润快照

每次跑流水线都新增一条，不覆盖。


| 字段                                            | 类型       | 说明            |
| --------------------------------------------- | -------- | ------------- |
| `selling_price`                               | REAL     | Amazon 定价     |
| `batch_qty`                                   | INTEGER  | 假定采购批量        |
| 各项成本明细                                        | REAL × 8 | 见 ORM 模型      |
| `total_cost` / `net_profit` / `profit_margin` | REAL     | 派生字段          |
| `params_version`                              | VARCHAR  | 参数版本号         |
| `params_snapshot`                             | JSON     | 当时 YAML 的完整快照 |


**为什么存派生字段而不是计算视图？** 派生字段允许直接 SQL 排序、分组、做 BI 报表，避免每次重算；同时保留原始明细可校验。

---

### `scores` — 评分

每次评分新增一条。


| 字段                              | 类型      | 说明                                      |
| ------------------------------- | ------- | --------------------------------------- |
| `profit_score` ... `risk_score` | REAL    | 6 个维度归一化得分（0-1）                         |
| `total_score`                   | REAL    | 综合得分（0-100）                             |
| `passed_hard_filter`            | BOOLEAN | 是否通过硬性筛选                                |
| `rejection_reasons`             | JSON    | 例如 `["margin_too_low", "moq_exceeded"]` |
| `weights_version`               | VARCHAR | 权重版本号                                   |
| `weights_snapshot`              | JSON    | 当时的权重 + 曲线 YAML 快照                      |


索引：`total_score`、`passed_hard_filter`、`scored_at`。

---

### `market_analyses` — 卖家精灵市场数据


| 字段                       | 说明                           |
| ------------------------ | ---------------------------- |
| `main_keyword`           | 反查出的主关键词                     |
| `search_volume_monthly`  | 月搜索量                         |
| `keyword_difficulty`     | 关键词难度（0-100）                 |
| `competing_listings`     | 在售竞品数                        |
| `top10_revenue_share`    | Top 10 收入集中度（0-1）            |
| `avg_review_count_top10` | Top 10 平均评论数                 |
| `avg_price_top10`        | Top 10 平均价                   |
| `opportunity_score`      | 机会度评分（卖家精灵原始）                |
| `seasonality`            | JSON `{"month_1": 0.8, ...}` |
| `raw_data`               | API 原始返回                     |


---

### `run_logs` — 流水线执行日志

独立表，记录每次流水线运行的元数据：


| 字段                                               | 说明                                                              |
| ------------------------------------------------ | --------------------------------------------------------------- |
| `pipeline_version`                               | 代码版本（git tag）                                                   |
| `category` / `marketplace`                       | 本次跑的范围                                                          |
| `products_crawled` ... `candidates_after_filter` | 各阶段计数                                                           |
| `api_calls`                                      | JSON `{"keepa": 50, "alibaba_pailitao": 30, "mjjl": 20}`，便于成本审计 |
| `status`                                         | `running` / `success` / `failed` / `aborted`                    |
| `started_at` / `finished_at`                     | 时间                                                              |


---

## 视图

### `v_latest_scores`

每个产品的最新评分 + 是否通过筛选，方便业务查询。

```sql
SELECT * FROM v_latest_scores
WHERE passed_hard_filter = 1
ORDER BY total_score DESC
LIMIT 20;
```

---

## 常用查询

**Top 20 候选选品（最新评分 + 利润 + Top 1 货源）：**

```sql
SELECT
    p.asin, p.title, p.price, p.bsr_rank,
    s.total_score, s.passed_hard_filter,
    pf.net_profit, pf.profit_margin,
    sup.supplier_name, sup.base_price_cny, sup.moq
FROM products p
JOIN scores s            ON s.id  = (SELECT id FROM scores            WHERE product_id = p.id ORDER BY scored_at  DESC LIMIT 1)
JOIN profit_snapshots pf ON pf.id = (SELECT id FROM profit_snapshots WHERE product_id = p.id ORDER BY snapshot_at DESC LIMIT 1)
JOIN suppliers sup       ON sup.id = pf.supplier_id
WHERE s.passed_hard_filter = 1
ORDER BY s.total_score DESC
LIMIT 20;
```

**参数版本对比（同一产品两次评分差异）：**

```sql
SELECT
    p.asin,
    s1.total_score AS score_v1, s1.weights_version AS v1,
    s2.total_score AS score_v2, s2.weights_version AS v2,
    s2.total_score - s1.total_score AS delta
FROM products p
JOIN scores s1 ON s1.product_id = p.id AND s1.weights_version = '0.1.0'
JOIN scores s2 ON s2.product_id = p.id AND s2.weights_version = '0.2.0'
ORDER BY delta DESC;
```

---

## 迁移建议

- 开发期：SQLite + `Base.metadata.create_all()`
- 多人共享后：迁 PostgreSQL，启用 Alembic 做版本化 migration
- 数据量过 1000 万行：考虑 `products` 按 `marketplace` 分表

