# 评分规则详解

> 配置文件：`config/scoring_weights.yaml`

## 总分公式

$$\text{totalscore} = \sum_{d \in D} (\text{score}_d \times w_d) \times 100$$

其中 $D = \text{demand, profit, competition, supply, logistics, risk}$，$\sum w_d = 1$。

每个 $\text{score}_d \in [0, 1]$，总分范围 0–100。

**判断参考**（来自真实选品评分表）：


| 总分    | 建议          |
| ----- | ----------- |
| < 50  | 不做（硬性淘汰）    |
| 50–64 | 看起来不错，需人工复核 |
| ≥ 65  | 推荐，进入候选池    |


**优先级原则**：需求 > 利润 > 竞争 > 可行性

---

## 各维度详解

### 1. 市场需求 `demand_score`（权重 25%，最高优先级）

**输入**：`opportunity_score`（机会指数）、`daily_revenue_top100`、`daily_sales_top20`、`search_volume_monthly`、`bsr_rank`、`monthly_sales`、`price`、`core_keywords_count`、`google_trends_up`

**逻辑**：五因子复合

```
# 因子1：机会指数（卖家精灵）
opp_score = 1.0 if opportunity_score > 0.05 else 0.0

# 因子2：Top100 日均销售额
revenue_score = min(1, daily_revenue_top100 / 50)   # $50 为满分线

# 因子3：Top20 日均销量
sales_score = min(1, daily_sales_top20 / 10)

# 因子4：核心词月搜索量
kw_score = min(1, search_volume_monthly / 2000)

# 因子5：BSR + 月销量（辅助）
bsr_score = max(0, 1 - log(bsr) / log(50000))
monthly_score = min(1, monthly_sales / 300)
bsr_combined = 0.5 × bsr_score + 0.5 × monthly_score

# 合成（机会指数权重最高）
base = 0.30×opp_score + 0.25×revenue_score + 0.20×sales_score
     + 0.15×kw_score + 0.10×bsr_combined

# 奖励：Google Trends 趋势向上
demand_score = min(1, base + 0.10 if google_trends_up else base)
```

**价格区间检查**：售价 < $15 且利润率未达 30% 时，`demand_score` 最高取 0.5。


| 机会指数   | Top100日均销售额 | 搜索量       | 得分     |
| ------ | ----------- | --------- | ------ |
| > 0.05 | > $50       | > 2000    | ≈ 0.9+ |
| ≈ 0.05 | $30–$50     | 1000–2000 | ≈ 0.6  |
| < 0.05 | < $30       | < 1000    | ≈ 0.2  |


---

### 2. 利润率 `profit_score`（权重 20%）

**输入**：`profit_margin`（净利率，由 `profit_model.predict_profit` 计算）

**曲线**：sigmoid 形状


| 净利率        | 得分    |
| ---------- | ----- |
| ≤ 10%      | 0     |
| 20%（最低容忍线） | ≈ 0.3 |
| 30%（目标）    | ≈ 0.5 |
| ≥ 50%      | 1     |


**利润计算公式**（来自真实目标采购成本表）：

$$\text{净利润} = \text{售价} - (\text{采购} + \text{头程} + \text{FBA} + \text{佣金} + \text{广告} + \text{退货} + \text{汇率损耗})$$

各项默认费率：


| 费项      | 默认值  | 说明                  |
| ------- | ---- | ------------------- |
| 平台佣金    | 15%  | 按类目查表（电子 8%，服装 17%） |
| 广告 ACOS | 25%  | 目标 <25%，新品期 35%     |
| 退货率     | 6%   | 一般类目（服装 20%，电子 12%） |
| 退货损耗比   | 30%  | 退回货中不可二次销售比例        |
| 汇率损耗    | 1%   | 收付款汇差               |
| 汇率      | 6.88 | 1 USD ≈ 6.88 CNY    |


---

### 3. 竞争烈度 `competition_score`（权重 20%）

**输入**：`competing_listings`、`top10_revenue_share`、`top4_sales_share`（前四名销量占首页比例）、`has_brand_monopoly`（首页有国际品牌）、`bsr20_low_review_count`

**逻辑**：多因子叠加

```
# 基础：卖家数量
sellers_score = clamp(1 - (n - 20) / (200 - 20), 0, 1)

# 惩罚1：前四名销量占首页 > 40%（市场高度集中）
if top4_sales_share > 0.40:
    sellers_score *= 0.7

# 惩罚2：头部收入集中度（Top10 > 60%）
if top10_revenue_share > 0.6:
    sellers_score *= 0.5

# 惩罚3：国际品牌垄断首页
if has_brand_monopoly:
    sellers_score *= 0.5

# 奖励：BSR 前 20 有 ≥ 5 个 Review < 100（新品有机会入场）
if bsr20_low_review_count >= 5:
    sellers_score = min(1, sellers_score + 0.10)

competition_score = sellers_score
```

**关键规则（来自真实选品评分表）**：

- 前四名销量占首页 < 40% → 市场分散，新品有机会（6 分）
- 无国际品牌占据首页（10 分，权重最高的竞争项）
- BSR 前 20 有 ≥ 5 个低评论产品 → 竞争门槛低（3 分）

---

### 4. 货源稳定性 `supply_score`（权重 15%）

**输入**：`suppliers`（列表），每个供应商含 `moq`、`repeat_buyer_rate`、`delivery_days`、`fba_ready`、`base_price_cny`

**逻辑**：

```
n_score        = min(1, len(suppliers) / 3)
repeat_avg     = mean([s.repeat_buyer_rate for s in suppliers])
moq_min        = min([s.moq for s in suppliers])
moq_score      = 1 if moq_min <= 100 else 100 / moq_min

# 交期评分（供货周期 < 25 天满分）
delivery_min   = min([s.delivery_days for s in suppliers], default=999)
delivery_score = clamp(1 - delivery_min / 25, 0, 1)

# 首单资金检查（≤ 5 万 CNY 满分）
initial_cny    = moq_min × best_price_cny
capital_score  = 1.0 if initial_cny <= 50000 else 50000 / initial_cny

# FBA 经验奖励
fba_bonus = 0.08 if any(s.fba_ready for s in suppliers) else 0

base = 0.30×n_score + 0.30×repeat_avg + 0.15×moq_score
     + 0.15×delivery_score + 0.10×capital_score
supply_score = min(1, base + fba_bonus)
```

---

### 5. 物流友好度 `logistics_score`（权重 10%）

**输入**：`weight_kg`、`length_cm × width_cm × height_cm`、产品属性

**逻辑**：

```
# 危险属性黑名单（命中任一直接 0 分）
if 命中黑名单属性（带电、液体、易碎、磁性）:
    return 0

# 体积重比（来自真实选品评分表：体积重 < 实重 × 1.2）
volumetric_kg = L_cm × W_cm × H_cm / 6000
vol_ratio = volumetric_kg / weight_kg
ratio_score = 1 if vol_ratio <= 1.2 else clamp(1.2 / vol_ratio, 0, 1)

# 重量得分
weight_score = clamp(1 - weight_kg / 2.0, 0, 1)

# 最长边得分
size_score = clamp(1 - longest_side_cm / 45.0, 0, 1)

logistics_score = 0.40×ratio_score + 0.35×weight_score + 0.25×size_score
```


| 场景   | 体积重比  | 重量     | 最长边   | 得分     |
| ---- | ----- | ------ | ----- | ------ |
| 小件轻货 | ≤ 1.2 | 0.5 kg | 20 cm | ≈ 0.85 |
| 中等货品 | 1.5   | 1.5 kg | 35 cm | ≈ 0.45 |
| 带电产品 | 任意    | 任意     | 任意    | 0      |


---

### 6. 风险等级 `risk_score`（权重 10%）

**输入**：`category`、`brand`、`seasonality`（12 个月销售额序列）

**逻辑**：从 1.0 开始递减

```
score = 1.0

if brand 命中知名品牌词:
    score *= 0.5

if category in 强制认证类目（CPC / FCC / FDA）:
    score *= 0.7

# 季节性风险（季节性不明显权重高，来自真实评分表）
cv = std(monthly_sales) / mean(monthly_sales)   # 月销售额变异系数
if cv > 0.4:
    score *= 0.7

risk_score = score
```

---

## 硬性筛选

不经过加权，直接淘汰（仍写入 DB，`passed_hard_filter=False`）：


| 条件   | 阈值               | 来源依据                       |
| ---- | ---------------- | -------------------------- |
| 净利率  | < 20%            | 选品目标采购成本表（目标 30%，容忍最低 20%） |
| 总分   | < 50             | 选品评分表分级（50 分以下"不做"）        |
| 月销量  | < 200 件          | 选品思路文档（小卖家最低可行门槛）          |
| 平均售价 | < $15 且利润率 < 30% | 选品评分表价格区间条目                |
| MOQ  | > 500            | 选品评分表开发调研条目                |
| 供应商数 | = 0              | 无货源无法经营                    |
| 大品牌词 | 命中               | 侵权风险                       |


---

## 调参建议

1. **反向校准**：找 50 个已上架且结果清楚的产品（成功 / 失败各半），跑评分，看模型是否能区分。
2. **每次只动一个参数**：先调权重（结构性影响），再调曲线参数（细节）。
3. **保留版本号**：YAML 顶部加 `# version: x.y.z`，评分时记入 `weights_version` 字段，便于回归对比。
4. **参照人工两阶段评分**：`docs/选品参考/选品.xlsx` 的市场调研（100 分）和开发调研（100 分）可作为人工校准的对标基准。

---

## 单测覆盖

- 权重和必须 = 1.0（CI 校验，`tests/test_scoring.py::test_weights_sum_to_one`）
- 每个 `score_`* 函数：边界值（0 / target / 上限）+ 异常输入（None / 负值）
- `apply_hard_filters`：覆盖全部触发分支

