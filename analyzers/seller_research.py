"""
卖家研究规则引擎
================

把卖家精灵「查竞品 / 选市场」导出的竞品级数据，按卖家聚合，判定哪些卖家/产品
更适合中小卖家研究参考，并给出 0–100 的综合适合度与可解释的规则理由。

设计原则：
- 纯函数 + 可注入配置，便于单测；不做任何网络/浏览器副作用。
- 证据驱动：缺失字段不臆造，只影响可判定性（记为数据不足并排除）。
- 阈值全部来自 config/seller_research_rules.yaml（可热加载）。

规则与曲线：config/seller_research_rules.yaml
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from config.settings import CONFIG_DIR

_RULES_CACHE: Optional[dict] = None
_WEIGHT_SUM_TOLERANCE = 1e-6

# 归一化后的排序类别顺序（越靠前越优先展示给中小卖家）
CATEGORY_ORDER = (
    "low_competition_efficient",
    "new_rising",
    "differentiation_opportunity",
    "stable_niche",
)


# ============================================================
# 配置加载
# ============================================================
def load_rules_config(path: Optional[Path] = None) -> dict:
    """加载并缓存卖家研究规则；显式传 path 时不走缓存。"""
    global _RULES_CACHE
    if path is None and _RULES_CACHE is not None:
        return _RULES_CACHE
    config_path = path or CONFIG_DIR / "seller_research_rules.yaml"
    with open(config_path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    _validate_config(config)
    if path is None:
        _RULES_CACHE = config
    return config


def reload_rules_config() -> dict:
    """丢弃缓存并重新加载（改 YAML 后热更新）。"""
    global _RULES_CACHE
    _RULES_CACHE = None
    return load_rules_config()


def config_for_category(base: dict, category: Optional[str]) -> dict:
    """Deep-merge a target category's profile over the base rules.

    ``category`` uses the canonical ids from ``domain.target_categories``
    (e.g. ``patio_furniture_sets``).  Unknown/empty categories return the base
    config unchanged so generic niches keep the default thresholds.
    """
    if not category:
        return base
    profiles = base.get("category_profiles") or {}
    override = profiles.get(category)
    if not isinstance(override, dict):
        return base
    merged = _deep_merge(base, override)
    merged["resolved_category"] = category
    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = value
    return result


def _validate_config(config: dict) -> None:
    if not isinstance(config, dict):
        raise ValueError("seller_research_rules.yaml 顶层必须是映射")
    for key in ("exclusions", "categories", "fit_score"):
        if key not in config:
            raise ValueError(f"seller_research_rules.yaml 缺少必需段：{key}")
    weights = (config.get("fit_score") or {}).get("weights") or {}
    total = sum(float(v) for v in weights.values())
    if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
        raise ValueError(f"fit_score.weights 之和必须为 1.0，当前为 {total}")


# ============================================================
# 数据容器
# ============================================================
@dataclass(frozen=True)
class CompetitorRow:
    """一条竞品级产品数据（卖家精灵导出并归一化后的单行）。"""

    seller: Optional[str] = None
    asin: Optional[str] = None
    title: Optional[str] = None
    brand: Optional[str] = None
    price: Optional[float] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    launch_date: Optional[str] = None          # ISO 日期字符串
    monthly_sales: Optional[int] = None
    monthly_revenue: Optional[float] = None
    seller_product_count: Optional[int] = None  # 卖家在售商品数（导出若提供）
    raw: dict[str, Any] = field(default_factory=dict)

    def launch_months(self, as_of: date) -> Optional[float]:
        parsed = _parse_date(self.launch_date)
        if parsed is None:
            return None
        days = (as_of - parsed).days
        return round(max(0.0, days) / 30.4375, 2)


@dataclass
class SellerResearchItem:
    """一个卖家在该类目下的研究结论。"""

    seller: str
    representative_asin: Optional[str]
    representative_title: Optional[str]
    brand: Optional[str]
    price: Optional[float]
    rating: Optional[float]
    review_count: Optional[int]
    launch_date: Optional[str]
    launch_months: Optional[float]
    monthly_sales: Optional[int]
    monthly_revenue: Optional[float]
    seller_product_count: Optional[int]
    product_count_source: str            # "reported" | "sample"
    fit_category: str
    fit_category_label: str
    fit_score: float
    fit_factors: dict[str, float]
    fit_reasons: list[str]
    excluded: bool = False
    exclusion_reasons: list[str] = field(default_factory=list)
    ai_reason: Optional[str] = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "seller": self.seller,
            "representative_asin": self.representative_asin,
            "representative_title": self.representative_title,
            "brand": self.brand,
            "price": self.price,
            "rating": self.rating,
            "review_count": self.review_count,
            "launch_date": self.launch_date,
            "launch_months": self.launch_months,
            "monthly_sales": self.monthly_sales,
            "monthly_revenue": self.monthly_revenue,
            "seller_product_count": self.seller_product_count,
            "product_count_source": self.product_count_source,
            "fit_category": self.fit_category,
            "fit_category_label": self.fit_category_label,
            "fit_score": self.fit_score,
            "fit_factors": self.fit_factors,
            "fit_reasons": self.fit_reasons,
            "excluded": self.excluded,
            "exclusion_reasons": self.exclusion_reasons,
            "ai_reason": self.ai_reason,
        }


@dataclass
class SellerShortlist:
    """一次卖家研究的完整结论。"""

    items: list[SellerResearchItem]
    excluded_items: list[SellerResearchItem]
    ruleset_version: str
    quality_summary: dict[str, Any]

    @property
    def eligible_count(self) -> int:
        return len(self.items)


# ============================================================
# 聚合 + 判定 + 评分
# ============================================================
def build_seller_shortlist(
    rows: list[CompetitorRow],
    *,
    config: Optional[dict] = None,
    category: Optional[str] = None,
    as_of: Optional[date] = None,
) -> SellerShortlist:
    """从竞品行聚合出卖家清单，完成排除、归类、评分与规则理由。

    传入 ``category``（四个目标户外品类的规范 id）时，自动把该品类的
    阈值覆盖深合并到基础规则之上。
    """
    config = config or load_rules_config()
    config = config_for_category(config, category)
    as_of = as_of or datetime.utcnow().date()

    aggregates = _aggregate_by_seller(rows, config)
    brand_shares = _brand_shares([row for row in rows if row.brand])

    eligible: list[SellerResearchItem] = []
    excluded: list[SellerResearchItem] = []
    for aggregate in aggregates:
        item = _classify_and_score(aggregate, config, brand_shares, as_of)
        if item.excluded:
            excluded.append(item)
        else:
            eligible.append(item)

    eligible.sort(key=lambda entry: (entry.fit_score, entry.monthly_sales or 0), reverse=True)
    excluded.sort(key=lambda entry: (entry.fit_score, entry.monthly_sales or 0), reverse=True)

    quality_summary = {
        "source_row_count": len(rows),
        "seller_count": len(aggregates),
        "eligible_count": len(eligible),
        "excluded_count": len(excluded),
        "category_counts": _category_counts(eligible),
        "scored_count": len(eligible) + len(excluded),
        "score_summary": _score_summary([*eligible, *excluded]),
        "resolved_category": config.get("resolved_category"),
    }
    return SellerShortlist(
        items=eligible,
        excluded_items=excluded,
        ruleset_version=str(config.get("version") or "unknown"),
        quality_summary=quality_summary,
    )


def _aggregate_by_seller(rows: list[CompetitorRow], config: dict) -> list[dict[str, Any]]:
    representative_by = ((config.get("aggregation") or {}).get("representative_by")) or "monthly_revenue"
    buckets: dict[str, list[CompetitorRow]] = {}
    for row in rows:
        seller = (row.seller or "").strip()
        if not seller:
            continue
        buckets.setdefault(seller, []).append(row)

    aggregates: list[dict[str, Any]] = []
    for seller, seller_rows in buckets.items():
        representative = _pick_representative(seller_rows, representative_by)
        reported = _first_not_none(row.seller_product_count for row in seller_rows)
        aggregates.append(
            {
                "seller": seller,
                "rows": seller_rows,
                "representative": representative,
                "reported_product_count": reported,
                "sample_product_count": len(seller_rows),
                "total_monthly_sales": _sum_optional(row.monthly_sales for row in seller_rows),
                "total_monthly_revenue": _sum_optional(row.monthly_revenue for row in seller_rows),
                "brands": sorted({row.brand for row in seller_rows if row.brand}),
            }
        )
    return aggregates


def _pick_representative(rows: list[CompetitorRow], representative_by: str) -> CompetitorRow:
    def sort_key(row: CompetitorRow) -> tuple[float, float]:
        primary = getattr(row, representative_by, None)
        secondary = row.monthly_sales
        return (_num(primary), _num(secondary))

    return max(rows, key=sort_key)


def _classify_and_score(
    aggregate: dict[str, Any],
    config: dict,
    brand_shares: dict[str, float],
    as_of: date,
) -> SellerResearchItem:
    rep: CompetitorRow = aggregate["representative"]
    reported = aggregate["reported_product_count"]
    product_count = reported if reported is not None else aggregate["sample_product_count"]
    product_count_source = "reported" if reported is not None else "sample"
    launch_months = rep.launch_months(as_of)

    item = SellerResearchItem(
        seller=aggregate["seller"],
        representative_asin=rep.asin,
        representative_title=rep.title,
        brand=rep.brand,
        price=rep.price,
        rating=rep.rating,
        review_count=rep.review_count,
        launch_date=rep.launch_date,
        launch_months=launch_months,
        monthly_sales=rep.monthly_sales,
        monthly_revenue=rep.monthly_revenue,
        seller_product_count=product_count,
        product_count_source=product_count_source,
        fit_category="",
        fit_category_label="",
        fit_score=0.0,
        fit_factors={},
        fit_reasons=[],
    )

    # The opportunity score is calculated for every aggregate, including
    # records that fail a hard admission rule.  That keeps a high-demand
    # product visible in the market-research ranking while its exclusion
    # reason still prevents it from being presented as a recommended entry.
    category_key, label, reasons = _match_category(item, product_count, launch_months, config)
    score, factors = compute_fit_score(item, product_count, launch_months, config)
    item.fit_category = category_key
    item.fit_category_label = label
    item.fit_reasons = reasons
    item.fit_score = score
    item.fit_factors = factors

    exclusion_reasons = _exclusion_reasons(item, config, brand_shares)
    if exclusion_reasons:
        item.excluded = True
        item.exclusion_reasons = exclusion_reasons
        item.fit_category = "excluded"
        item.fit_category_label = "不适合参考"
        return item
    return item


def _exclusion_reasons(
    item: SellerResearchItem,
    config: dict,
    brand_shares: dict[str, float],
) -> list[str]:
    rules = config.get("exclusions") or {}
    reasons: list[str] = []

    for field_name in rules.get("require_fields") or []:
        if getattr(item, field_name, None) is None:
            reasons.append(f"数据不足：缺少{_field_label(field_name)}")

    head_reviews = rules.get("head_seller_review_count")
    if head_reviews is not None and item.review_count is not None and item.review_count >= head_reviews:
        reasons.append(f"头部卖家：评论数 {item.review_count} ≥ {head_reviews}")

    head_revenue = rules.get("head_seller_monthly_revenue")
    if head_revenue is not None and item.monthly_revenue is not None and item.monthly_revenue >= head_revenue:
        reasons.append(f"成熟大卖：月销售额 ${item.monthly_revenue:,.0f} ≥ ${head_revenue:,.0f}")

    share_threshold = rules.get("brand_monopoly_share")
    min_samples = rules.get("brand_monopoly_min_samples") or 0
    if (
        share_threshold is not None
        and item.brand
        and sum(brand_shares.values()) >= 0  # brand_shares 已是占比
        and brand_shares.get("__total_samples__", 0) >= min_samples
    ):
        share = brand_shares.get(item.brand.strip().casefold(), 0.0)
        if share >= share_threshold:
            reasons.append(f"品牌垄断：{item.brand} 占样本 {share:.0%} ≥ {share_threshold:.0%}")

    return reasons


def _match_category(
    item: SellerResearchItem,
    product_count: Optional[int],
    launch_months: Optional[float],
    config: dict,
) -> tuple[str, str, list[str]]:
    categories = config.get("categories") or {}

    for key in CATEGORY_ORDER:
        rule = categories.get(key)
        if not rule:
            continue
        matched, reasons = _category_matches(key, rule, item, product_count, launch_months)
        if matched:
            return key, str(rule.get("label_zh") or key), reasons

    fallback = categories.get("stable_niche") or {}
    return "stable_niche", str(fallback.get("label_zh") or "稳健利基型"), ["指标平稳，适合稳妥研究"]


def _category_matches(
    key: str,
    rule: dict,
    item: SellerResearchItem,
    product_count: Optional[int],
    launch_months: Optional[float],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if key == "low_competition_efficient":
        max_products = rule.get("max_seller_product_count")
        min_revenue = rule.get("min_monthly_revenue")
        min_sales = rule.get("min_monthly_sales")
        if not _le(product_count, max_products):
            return False, []
        if not _ge(item.monthly_revenue, min_revenue):
            return False, []
        if not _ge(item.monthly_sales, min_sales):
            return False, []
        reasons.append(f"仅 {product_count} 款在售却月销 {item.monthly_sales} 件，少而精")
        return True, reasons

    if key == "new_rising":
        if launch_months is None:
            return False, []
        if not _le(launch_months, rule.get("max_launch_months")):
            return False, []
        if not _le(item.review_count, rule.get("max_review_count")):
            return False, []
        if not _ge(item.monthly_sales, rule.get("min_monthly_sales")):
            return False, []
        reasons.append(f"上架约 {launch_months:.0f} 个月、评论 {item.review_count or 0} 条已跑出月销 {item.monthly_sales} 件")
        return True, reasons

    if key == "differentiation_opportunity":
        if item.rating is None:
            return False, []
        if not _ge(item.rating, rule.get("min_rating")):
            return False, []
        if not _le(item.rating, rule.get("max_rating")):
            return False, []
        if not _ge(item.monthly_sales, rule.get("min_monthly_sales")):
            return False, []
        if not _le(item.review_count, rule.get("max_review_count")):
            return False, []
        reasons.append(f"评分 {item.rating} 有改进空间，月销 {item.monthly_sales} 件说明需求真实")
        return True, reasons

    if key == "stable_niche":
        if not _ge(item.monthly_sales, rule.get("min_monthly_sales")):
            return False, []
        return True, ["指标平稳，适合稳妥研究"]

    return False, []


def compute_fit_score(
    item: SellerResearchItem,
    product_count: Optional[int],
    launch_months: Optional[float],
    config: dict,
) -> tuple[float, dict[str, float]]:
    fit = config.get("fit_score") or {}
    weights = fit.get("weights") or {}
    curves = fit.get("curves") or {}

    demand = _ramp_high_good(
        item.monthly_sales, 0.0, curves.get("demand_monthly_sales_target", 500)
    )
    review_component = _ramp_low_good(
        item.review_count,
        curves.get("competition_review_count_good", 200),
        curves.get("competition_review_count_poor", 3000),
    )
    product_component = _ramp_low_good(
        product_count,
        curves.get("competition_product_count_good", 10),
        curves.get("competition_product_count_poor", 60),
    )
    low_competition = round((review_component + product_component) / 2, 4)
    freshness = _ramp_low_good(
        launch_months,
        curves.get("freshness_launch_months_good", 6),
        curves.get("freshness_launch_months_poor", 36),
    )
    differentiation = _differentiation_room(
        item.rating,
        curves.get("differentiation_ideal_low", 3.8),
        curves.get("differentiation_ideal_high", 4.3),
    )

    factors = {
        "demand_proven": demand,
        "low_competition": low_competition,
        "freshness": freshness,
        "differentiation_room": differentiation,
    }
    score = 0.0
    for name, value in factors.items():
        score += float(weights.get(name, 0.0)) * value
    return round(score * 100, 1), factors


# ============================================================
# 归一化与数值工具
# ============================================================
def _ramp_high_good(value: Any, low: float, high: float) -> float:
    """值越高越好：<= low 记 0，>= high 记 1，线性过渡。value 缺失记中性 0.5。"""
    number = _to_number(value)
    if number is None:
        return 0.5
    if high <= low:
        return 1.0 if number >= high else 0.0
    return _clamp((number - low) / (high - low))


def _ramp_low_good(value: Any, good: float, poor: float) -> float:
    """值越低越好：<= good 记 1，>= poor 记 0，线性过渡。value 缺失记中性 0.5。"""
    number = _to_number(value)
    if number is None:
        return 0.5
    if poor <= good:
        return 1.0 if number <= good else 0.0
    return _clamp((poor - number) / (poor - good))


def _differentiation_room(rating: Any, ideal_low: float, ideal_high: float) -> float:
    number = _to_number(rating)
    if number is None:
        return 0.5
    if ideal_low <= number <= ideal_high:
        return 1.0
    if number < ideal_low:
        # 评分过低多为质量硬伤，从 ideal_low 线性降到 3.0
        return _clamp((number - 3.0) / max(ideal_low - 3.0, 1e-6))
    # 评分过高（趋近满分）差异化空间小，从 ideal_high 线性降到 5.0
    return _clamp((5.0 - number) / max(5.0 - ideal_high, 1e-6))


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _brand_shares(rows: list[CompetitorRow]) -> dict[str, float]:
    total = len(rows)
    shares: dict[str, float] = {"__total_samples__": float(total)}
    if total == 0:
        return shares
    counts: dict[str, int] = {}
    for row in rows:
        key = (row.brand or "").strip().casefold()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    for key, count in counts.items():
        shares[key] = count / total
    return shares


def _category_counts(items: list[SellerResearchItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.fit_category] = counts.get(item.fit_category, 0) + 1
    return counts


def _score_summary(items: list[SellerResearchItem]) -> dict[str, float | int | None]:
    """Return a compact, non-misleading summary of all opportunity scores."""
    scores = sorted(item.fit_score for item in items)
    if not scores:
        return {"average": None, "median": None, "max": None, "min": None}
    midpoint = len(scores) // 2
    median = scores[midpoint] if len(scores) % 2 else round((scores[midpoint - 1] + scores[midpoint]) / 2, 1)
    return {
        "average": round(sum(scores) / len(scores), 1),
        "median": median,
        "max": scores[-1],
        "min": scores[0],
    }


def _field_label(field_name: str) -> str:
    return {
        "monthly_sales": "月销量",
        "monthly_revenue": "月销售额",
        "price": "价格",
        "rating": "评分",
        "review_count": "评论数",
    }.get(field_name, field_name)


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%m/%d/%Y", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _to_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _num(value: Any) -> float:
    number = _to_number(value)
    return number if number is not None else float("-inf")


def _sum_optional(values: Any) -> Optional[float]:
    total = 0.0
    seen = False
    for value in values:
        number = _to_number(value)
        if number is not None:
            total += number
            seen = True
    return total if seen else None


def _first_not_none(values: Any) -> Optional[Any]:
    for value in values:
        if value is not None:
            return value
    return None


def _ge(value: Any, threshold: Any) -> bool:
    if threshold is None:
        return True
    number = _to_number(value)
    return number is not None and number >= float(threshold)


def _le(value: Any, threshold: Any) -> bool:
    if threshold is None:
        return True
    number = _to_number(value)
    return number is not None and number <= float(threshold)
