"""
评分引擎
========

输入：一个 product 的全部数据（profit、market、supplier 等）
输出：6 个维度归一化得分 + 综合分（0-100）+ 是否通过硬性筛选

权重和曲线参数：config/scoring_weights.yaml（可热加载）

设计原则：
    1. 每个 score_* 函数纯函数无副作用，方便单测
    2. 权重存 YAML，调参不动代码
    3. 总分 = sum(dim_score × weight) × 100
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from loguru import logger

from analyzers.profit_model import normalize_positive_number, normalize_price_tier

from config.settings import CONFIG_DIR

_BRAND_BLACKLIST = {
    "apple", "samsung", "sony", "nike", "adidas", "lego", "dyson",
    "instant pot", "kitchenaid", "cuisinart", "breville", "philips",
    "bosch", "de'longhi", "delonghi", "shark", "roomba", "irobot",
}


class ScoringEvidenceError(ValueError):
    def __init__(self, dimension: str, fields: list[str]):
        self.dimension = dimension
        self.fields = fields
        super().__init__(f"missing {dimension} evidence: {','.join(fields)}")


# ============================================================
# DTO
# ============================================================
@dataclass
class ScoreBreakdown:
    profit_score: float = 0.0
    demand_score: float = 0.0
    competition_score: float = 0.0
    supply_score: float = 0.0
    logistics_score: float = 0.0
    risk_score: float = 0.0
    total_score: float = 0.0
    passed_hard_filter: bool = False
    rejection_reasons: list[str] = field(default_factory=list)


# ============================================================
# 配置加载
# ============================================================
_WEIGHTS_CACHE: Optional[dict] = None


def load_weights_config(path: Optional[Path] = None) -> dict:
    global _WEIGHTS_CACHE
    if _WEIGHTS_CACHE is not None:
        return _WEIGHTS_CACHE
    path = path or CONFIG_DIR / "scoring_weights.yaml"
    with open(path, "r", encoding="utf-8") as f:
        _WEIGHTS_CACHE = yaml.safe_load(f)
    weights = _WEIGHTS_CACHE["weights"]
    s = sum(weights.values())
    if abs(s - 1.0) > 1e-6:
        raise ValueError(f"权重和必须为 1.0，当前 {s}")
    logger.debug(f"Loaded scoring weights from {path}")
    return _WEIGHTS_CACHE


def reload_weights_config() -> None:
    global _WEIGHTS_CACHE
    _WEIGHTS_CACHE = None


# ============================================================
# 工具函数
# ============================================================
def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _sigmoid(x: float, center: float, k: float) -> float:
    return 1.0 / (1.0 + math.exp(-k * (x - center)))


def _contains_any_keyword(text: str, keywords: list[str]) -> bool:
    haystack = (text or "").lower()
    return any(str(k).lower() in haystack for k in keywords if str(k).strip())


def _first_number(*values) -> Optional[float]:
    """返回第一个可用数字，避免把搜索量误当成销量等语义串线。"""
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _supplier_raw_data(supplier) -> dict:
    raw = getattr(supplier, "raw_data", None)
    return raw if isinstance(raw, dict) else {}


def _supplier_raw_number(supplier, key: str) -> Optional[float]:
    value = _supplier_raw_data(supplier).get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _supplier_number(supplier, attr: str, raw_key: Optional[str] = None) -> Optional[float]:
    value = getattr(supplier, attr, None)
    try:
        return float(value)
    except (TypeError, ValueError):
        return _supplier_raw_number(supplier, raw_key or attr)


def _supplier_spec_match(supplier) -> dict:
    spec = _supplier_raw_data(supplier).get("spec_match")
    return spec if isinstance(spec, dict) else {}


def _target_category_id(product) -> str | None:
    raw = getattr(product, "raw_data", None)
    profile = (raw or {}).get("target_category_profile") if isinstance(raw, dict) else None
    value = profile.get("category_id") if isinstance(profile, dict) else None
    return str(value) if value else None


# ============================================================
# 单维度归一化函数（纯函数，便于单测）
# ============================================================

def score_profit(profit_margin: float, curve: dict) -> float:
    """利润率 → [0,1]，sigmoid 曲线。

    floor 以下 → 0；ceiling 以上 → 1；target 处 ≈ 0.5。
    """
    floor: float = curve["floor"]     # 0.10
    target: float = curve["target"]   # 0.30
    ceiling: float = curve["ceiling"] # 0.50

    if profit_margin <= floor:
        return 0.0
    if profit_margin >= ceiling:
        return 1.0

    # k 使得 sigmoid(ceiling) ≈ 0.95
    k = math.log(19) / (ceiling - target)
    return _clamp(_sigmoid(profit_margin, target, k))


def score_demand(
    bsr_rank: Optional[int],
    monthly_sales: Optional[int],
    curve: dict,
    *,
    opportunity_score: Optional[float] = None,
    daily_revenue_top100: Optional[float] = None,
    daily_sales_top20: Optional[float] = None,
    search_volume_monthly: Optional[int] = None,
    price: Optional[float] = None,
    google_trends_up: bool = False,
) -> float:
    """五因子复合需求评分 → [0,1]。

    因子权重：机会指数(30%) + 日均销售额(25%) + 日均销量(20%) +
              搜索量(15%) + BSR/月销(10%)
    """
    c = curve

    # 因子1：机会指数
    opp = 1.0 if (opportunity_score or 0) > c.get("opportunity_score_threshold", 0.05) else 0.0

    # 因子2：Top100 日均销售额
    rev_target = c.get("daily_revenue_top100_min", 50)
    rev = _clamp((daily_revenue_top100 or 0) / rev_target) if rev_target else 0.0

    # 因子3：Top20 日均销量
    sales_target = c.get("daily_sales_top20_min", 10)
    day_sales = _clamp((daily_sales_top20 or 0) / sales_target) if sales_target else 0.0

    # 因子4：月搜索量
    sv_min = c.get("search_volume_min", 2000)
    kw = _clamp((search_volume_monthly or 0) / sv_min) if sv_min else 0.0

    # 因子5：BSR + 月销量（BSR 无数据时退回月销量）
    bsr_ok = c.get("bsr_acceptable", 50000)
    if bsr_rank and bsr_rank > 0 and bsr_ok > 1:
        bsr_s = _clamp(1 - math.log(bsr_rank) / math.log(bsr_ok))
    else:
        bsr_s = 0.5  # 无 BSR 数据时中性

    ms_target = c.get("monthly_sales_target", 300)
    ms_s = _clamp((monthly_sales or 0) / ms_target) if ms_target else 0.0

    bsr_combined = 0.5 * bsr_s + 0.5 * ms_s

    base = (0.30 * opp + 0.25 * rev + 0.20 * day_sales
            + 0.15 * kw + 0.10 * bsr_combined)

    # 价格区间惩罚：售价 < $15 且机会较低
    price_floor = c.get("price_floor", 15)
    if price and price < price_floor:
        base = min(base, 0.5)

    # Google Trends 奖励
    bonus = c.get("google_trends_bonus", 0.10) if google_trends_up else 0.0

    return _clamp(base + bonus)


def score_competition(
    competing_listings: Optional[int],
    top10_share: Optional[float],
    curve: dict,
    *,
    top4_sales_share: Optional[float] = None,
    has_brand_monopoly: bool = False,
    bsr20_low_review_count: Optional[int] = None,
) -> float:
    """竞争烈度 → [0,1]，越激烈越低。"""
    if competing_listings is None and top10_share is None:
        raise ScoringEvidenceError(
            "competition", ["competing_listings", "top10_share"]
        )
    c = curve
    n = competing_listings or 0

    sellers_low: int = c.get("sellers_low", 20)
    sellers_high: int = c.get("sellers_high", 200)
    rng = sellers_high - sellers_low
    s = _clamp(1 - (n - sellers_low) / rng) if rng else (1.0 if n <= sellers_low else 0.0)

    # 惩罚：前四名销量占首页 > 40%
    t4_thr = c.get("top4_sales_share_threshold", 0.40)
    if top4_sales_share and top4_sales_share > t4_thr:
        s *= c.get("top4_sales_share_penalty", 0.7)

    # 惩罚：Top10 收入占比 > 60%（寡头市场）
    t10_thr = c.get("top10_share_threshold", 0.6)
    if top10_share and top10_share > t10_thr:
        s *= c.get("top10_share_penalty", 0.5)

    # 惩罚：国际品牌垄断首页
    if has_brand_monopoly:
        s *= c.get("brand_monopoly_penalty", 0.5)

    # 奖励：BSR 前 20 有 ≥ 5 个低评论产品（新品入场机会）
    low_min = c.get("bsr20_low_review_count_min", 5)
    if bsr20_low_review_count and bsr20_low_review_count >= low_min:
        s = min(1.0, s + c.get("low_review_opportunity_bonus", 0.10))

    return _clamp(s)


def score_supply(suppliers: list, curve: dict) -> float:
    """货源稳定性 → [0,1]。

    六因子：供应商数量 + 回头率 + MOQ + 交期 + 初始资金 + 匹配质量
    """
    real_suppliers = []
    for supplier in suppliers:
        raw = _supplier_raw_data(supplier)
        method = getattr(supplier, "match_verification_method", None)
        if raw.get("source") == "mock" or raw.get("method") == "mock" or method == "mock":
            continue
        real_suppliers.append(supplier)
    if not real_suppliers:
        raise ScoringEvidenceError("supply", ["real_supplier"])

    evidenced = []
    suppliers_with_price = []
    suppliers_with_moq = []
    for supplier in real_suppliers:
        price = normalize_positive_number(_supplier_number(supplier, "base_price_cny"))
        if price is None:
            tiers = getattr(supplier, "price_tiers", None) or []
            price = next(
                (
                    normalized[1]
                    for tier in tiers
                    if (normalized := normalize_price_tier(tier)) is not None
                ),
                None,
            )
        moq = normalize_positive_number(_supplier_number(supplier, "moq"))
        if price is not None:
            suppliers_with_price.append(supplier)
        if moq is not None:
            suppliers_with_moq.append(supplier)
        if price is not None and moq is not None:
            evidenced.append(supplier)
    if not evidenced:
        if suppliers_with_price and suppliers_with_moq:
            fields = ["purchase_price", "moq"]
        else:
            fields = []
            if not suppliers_with_price:
                fields.append("purchase_price")
            if not suppliers_with_moq:
                fields.append("moq")
        raise ScoringEvidenceError("supply", fields)

    suppliers = evidenced

    c = curve

    # 供应商数量
    n_score = _clamp(len(suppliers) / c.get("min_suppliers", 3))

    # 平均回头率
    rates = [getattr(s, "repeat_buyer_rate", None) for s in suppliers]
    rates = [r for r in rates if r is not None]
    repeat_avg = sum(rates) / len(rates) if rates else 0.0

    # MOQ
    moqs = [getattr(s, "moq", None) for s in suppliers]
    moqs = [m for m in moqs if m is not None]
    moq_min = min(moqs) if moqs else None
    moq_ok = c.get("moq_acceptable", 100)
    moq_score = 1.0 if (moq_min is None or moq_min <= moq_ok) else _clamp(moq_ok / moq_min)

    # 交期
    days = [getattr(s, "delivery_days", None) for s in suppliers]
    days = [d for d in days if d is not None]
    delivery_target = c.get("delivery_days_target", 25)
    if days:
        delivery_min = min(days)
        delivery_score = _clamp(1 - delivery_min / delivery_target)
    else:
        delivery_score = 0.5  # 无数据时中性

    # 初始资金（首单成本 ≤ 5 万 CNY）
    prices = [normalize_positive_number(_supplier_number(s, "base_price_cny")) for s in suppliers]
    prices = [p for p in prices if p is not None]
    capital_max = c.get("initial_capital_max_cny", 50000)
    if moq_min is not None and prices:
        initial_cny = moq_min * min(prices)
        capital_score = 1.0 if initial_cny <= capital_max else _clamp(capital_max / initial_cny)
    else:
        capital_score = 0.5

    # 匹配质量（来自 verifier）
    match_scores = [
        getattr(s, "match_quality_score", None) for s in suppliers
        if getattr(s, "match_quality_score", None) is not None
    ]
    if match_scores:
        avg_match = sum(match_scores) / len(match_scores)
        match_target = c.get("match_quality_target", 0.6)
        match_score = _clamp(avg_match / match_target) if match_target else 0.5
    else:
        match_score = 0.5  # 无验证数据时中性

    # FBA 经验奖励
    fba_bonus = c.get("fba_ready_bonus", 0.08) if any(
        getattr(s, "fba_ready", False) for s in suppliers
    ) else 0.0

    factory_values = [getattr(s, "is_factory", None) for s in suppliers]
    known_factory = [v for v in factory_values if v is not None]
    factory_score = (
        sum(1.0 if v is True else 0.45 for v in known_factory) / len(known_factory)
        if known_factory else 0.65
    )

    monthly_sales = [
        getattr(s, "monthly_sales", None) for s in suppliers
        if getattr(s, "monthly_sales", None) is not None
    ]
    avg_supplier_sales = sum(monthly_sales) / len(monthly_sales) if monthly_sales else None
    supplier_sales_score = _clamp((avg_supplier_sales or 0) / 1000) if avg_supplier_sales is not None else 0.5

    base = (
        0.20 * n_score + 0.18 * repeat_avg + 0.12 * moq_score
        + 0.12 * delivery_score + 0.08 * capital_score + 0.15 * match_score
        + 0.10 * factory_score + 0.05 * supplier_sales_score
    )
    return _clamp(base + fba_bonus)


def score_logistics(
    weight_kg: Optional[float],
    length_cm: Optional[float],
    width_cm: Optional[float],
    height_cm: Optional[float],
    attrs: list,
    curve: dict,
) -> float:
    """物流友好度 → [0,1]。

    三因子：体积重比 + 重量 + 最长边
    危险属性黑名单命中则直接返回 0。
    """
    values = {
        "weight_kg": weight_kg,
        "length_cm": length_cm,
        "width_cm": width_cm,
        "height_cm": height_cm,
    }
    missing = [name for name, value in values.items() if value is None]
    if missing:
        raise ScoringEvidenceError("logistics", missing)
    c = curve
    blacklist = set(c.get("blacklist_attrs", []))
    if attrs and blacklist & set(str(a).lower() for a in attrs):
        return 0.0

    w = weight_kg or 0.5
    l = length_cm or 0.0
    wd = width_cm or 0.0
    h = height_cm or 0.0
    longest = max(l, wd, h) or 20.0

    # 体积重比
    vol_ratio_max = c.get("volumetric_ratio_max", 1.2)
    if l and wd and h:
        vol_kg = (l * wd * h) / 6000
        vol_ratio = vol_kg / w if w else 1.0
        ratio_score = 1.0 if vol_ratio <= vol_ratio_max else _clamp(vol_ratio_max / vol_ratio)
    else:
        ratio_score = 0.8  # 无尺寸数据时偏保守

    max_weight = c.get("max_weight_kg", 2.0)
    weight_score = _clamp(1 - w / max_weight)

    max_side = c.get("max_longest_side_cm", 45)
    size_score = _clamp(1 - longest / max_side)

    return _clamp(0.40 * ratio_score + 0.35 * weight_score + 0.25 * size_score)


def score_risk(
    category: Optional[str],
    brand: Optional[str],
    curve: dict,
    *,
    title: Optional[str] = None,
    seasonality: Optional[dict] = None,
) -> float:
    """风险等级 → [0,1]，从 1.0 递减。"""
    c = curve
    s = 1.0

    # 大品牌侵权
    if brand:
        brand_lower = brand.strip().lower()
        if brand_lower in _BRAND_BLACKLIST:
            s *= c.get("brand_blacklist_penalty", 0.5)

    # 强制认证类目
    blacklist_cats = c.get("blacklist_categories", [])
    cat = (category or "").strip()
    if any(cat.startswith(bc) or bc in cat for bc in blacklist_cats):
        s *= c.get("cert_required_penalty", 0.7)

    restricted_keywords = c.get("restricted_keywords", [])
    restricted_text = " ".join(filter(None, [title, category]))
    if _contains_any_keyword(restricted_text, restricted_keywords):
        s *= c.get("restricted_keyword_penalty", 0.4)

    # 季节性风险：月销售额变异系数 > 0.4
    if seasonality and isinstance(seasonality, dict):
        values = [v for v in seasonality.values() if isinstance(v, (int, float))]
        if len(values) >= 3:
            mean_v = sum(values) / len(values)
            if mean_v > 0:
                stdev_v = statistics.stdev(values)
                cv = stdev_v / mean_v
                cv_thr = c.get("seasonality_cv_threshold", 0.4)
                if cv > cv_thr:
                    s *= c.get("seasonality_penalty", 0.7)

    return _clamp(s)


# ============================================================
# 硬性筛选
# ============================================================

def apply_hard_filters(
    profit_margin: float,
    total_score: float,
    moq: Optional[int],
    supplier_count: int,
    brand: Optional[str],
    config: dict,
    *,
    product_title: Optional[str] = None,
    product_category: Optional[str] = None,
    monthly_sales: Optional[int] = None,
    selling_price: Optional[float] = None,
    top_supplier_match_quality: Optional[float] = None,
    top_supplier_spec_score: Optional[float] = None,
    top_supplier_spec_conflicts: Optional[list[str]] = None,
    top_supplier_candidate_score: Optional[float] = None,
    target_category_id: Optional[str] = None,
    top_supplier_target_decision: Optional[str] = None,
) -> tuple[bool, list[str]]:
    """返回 (是否通过, 拒绝原因列表)。"""
    hf = config["hard_filters"]
    reasons: list[str] = []

    if profit_margin < hf.get("min_net_profit_margin", 0.20):
        reasons.append("margin_too_low")

    if total_score < hf.get("min_total_score", 50):
        reasons.append("score_too_low")

    max_moq = hf.get("max_moq", 500)
    if moq is not None and moq > max_moq:
        reasons.append("moq_exceeded")

    if supplier_count < hf.get("min_supplier_count", 1):
        reasons.append("no_supplier")

    min_price = hf.get("min_avg_price", 15)
    if selling_price is not None and selling_price < min_price and profit_margin < 0.30:
        reasons.append("price_too_low")

    min_monthly = hf.get("min_monthly_sales", 200)
    if monthly_sales is not None and monthly_sales < min_monthly:
        reasons.append("monthly_sales_too_low")

    if hf.get("exclude_brand_listings", True) and brand:
        if brand.strip().lower() in _BRAND_BLACKLIST:
            reasons.append("brand_excluded")

    if hf.get("exclude_restricted_keywords", True):
        restricted_keywords = config.get("scoring_curves", {}).get("risk", {}).get(
            "restricted_keywords", []
        )
        restricted_text = " ".join(filter(None, [product_title, product_category]))
        if _contains_any_keyword(restricted_text, restricted_keywords):
            reasons.append("restricted_product")

    min_match = hf.get("min_top_supplier_match_quality")
    if (
        min_match is not None
        and top_supplier_match_quality is not None
        and top_supplier_match_quality < min_match
    ):
        reasons.append("supplier_match_too_low")

    min_spec = hf.get("min_top_supplier_spec_score")
    if (
        min_spec is not None
        and top_supplier_spec_score is not None
        and top_supplier_spec_score < min_spec
    ):
        reasons.append("supplier_spec_too_low")

    max_conflicts = hf.get("max_top_supplier_spec_conflicts")
    if max_conflicts is not None and top_supplier_spec_conflicts is not None:
        if len(top_supplier_spec_conflicts) > max_conflicts:
            reasons.append("supplier_spec_conflict")

    min_candidate = hf.get("min_top_supplier_candidate_score")
    if (
        min_candidate is not None
        and top_supplier_candidate_score is not None
        and top_supplier_candidate_score < min_candidate
    ):
        reasons.append("supplier_candidate_too_low")

    if target_category_id and top_supplier_target_decision != "keep":
        reasons.append("target_supplier_contract_not_passed")

    passed = len(reasons) == 0
    return passed, reasons


# ============================================================
# 主函数
# ============================================================

def score_product(
    product,
    profit_breakdown,
    market_analysis,
    suppliers: list,
    config: Optional[dict] = None,
) -> ScoreBreakdown:
    """对单个产品打分，返回 ScoreBreakdown。

    Args:
        product         ProductDTO 或 Product ORM
        profit_breakdown ProfitBreakdown（最优供应商利润）
        market_analysis  MarketAnalysisDTO / MarketAnalysis ORM，可为 None
        suppliers        list[SupplierDTO or Supplier ORM]
        config           scoring_weights.yaml 内容，None 时自动加载
    """
    config = config or load_weights_config()
    weights: dict = config["weights"]
    curves: dict = config["scoring_curves"]

    ma = market_analysis  # 简写

    # --- 各维度得分 ---
    estimated_monthly_sales = _first_number(
        getattr(ma, "est_monthly_sales", None),
        getattr(product, "estimated_monthly_sales", None),
    )
    estimated_daily_sales = _first_number(getattr(ma, "est_daily_sales", None))

    p_score = score_profit(
        profit_margin=profit_breakdown.profit_margin if profit_breakdown else 0.0,
        curve=curves["profit"],
    )

    d_score = score_demand(
        bsr_rank=getattr(product, "bsr_rank", None),
        monthly_sales=estimated_monthly_sales,
        curve=curves["demand"],
        opportunity_score=getattr(ma, "opportunity_score", None),
        daily_revenue_top100=None,   # 由卖家精灵扩展字段补充
        daily_sales_top20=estimated_daily_sales,
        search_volume_monthly=getattr(ma, "search_volume_monthly", None),
        price=getattr(product, "price", None),
        google_trends_up=False,
    )

    c_score = score_competition(
        competing_listings=getattr(ma, "competing_listings", None),
        top10_share=getattr(ma, "top10_revenue_share", None),
        curve=curves["competition"],
        top4_sales_share=None,
        has_brand_monopoly=False,
        bsr20_low_review_count=None,
    )

    s_score = score_supply(suppliers=suppliers, curve=curves["supply"])

    target_category_id = _target_category_id(product)
    logistics_curve = dict(curves["logistics"])
    target_profile = (config.get("target_category_profiles") or {}).get(
        target_category_id or "", {}
    )
    if isinstance(target_profile, dict):
        logistics_curve.update(target_profile.get("logistics") or {})
    l_score = score_logistics(
        weight_kg=getattr(product, "weight_kg", None),
        length_cm=getattr(product, "length_cm", None),
        width_cm=getattr(product, "width_cm", None),
        height_cm=getattr(product, "height_cm", None),
        attrs=[],
        curve=logistics_curve,
    )

    r_score = score_risk(
        category=getattr(product, "category", None),
        brand=getattr(product, "brand", None),
        curve=curves["risk"],
        title=getattr(product, "title", None),
        seasonality=getattr(ma, "seasonality", None),
    )

    # --- 综合得分 ---
    total = (
        weights["profit"]      * p_score +
        weights["demand"]      * d_score +
        weights["competition"] * c_score +
        weights["supply"]      * s_score +
        weights["logistics"]   * l_score +
        weights["risk"]        * r_score
    ) * 100

    # --- 硬性筛选 ---
    best_moq = min(
        (getattr(s, "moq", None) for s in suppliers if getattr(s, "moq", None) is not None),
        default=None,
    )
    top_supplier = suppliers[0] if suppliers else None
    top_spec = _supplier_spec_match(top_supplier) if top_supplier else {}
    top_target_evidence = (
        _supplier_raw_data(top_supplier).get("strict_match_evidence")
        if top_supplier else None
    )
    spec_conflicts = top_spec.get("conflicts") if top_spec else None
    if spec_conflicts is not None and not isinstance(spec_conflicts, list):
        spec_conflicts = [str(spec_conflicts)]
    passed, reasons = apply_hard_filters(
        profit_margin=profit_breakdown.profit_margin if profit_breakdown else 0.0,
        total_score=total,
        moq=best_moq,
        supplier_count=len(suppliers),
        brand=getattr(product, "brand", None),
        config=config,
        product_title=getattr(product, "title", None),
        product_category=getattr(product, "category", None),
        monthly_sales=estimated_monthly_sales,
        selling_price=getattr(product, "price", None),
        top_supplier_match_quality=_supplier_number(top_supplier, "match_quality_score") if top_supplier else None,
        top_supplier_spec_score=_first_number(top_spec.get("score")) if top_spec else None,
        top_supplier_spec_conflicts=spec_conflicts,
        top_supplier_candidate_score=_first_number(
            _supplier_raw_number(top_supplier, "supplier_rank_score") if top_supplier else None,
            _supplier_number(top_supplier, "candidate_score", "supplier_candidate_score") if top_supplier else None,
        ),
        target_category_id=target_category_id,
        top_supplier_target_decision=(
            top_target_evidence.get("decision")
            if isinstance(top_target_evidence, dict) else None
        ),
    )

    logger.info(
        f"scored | asin={getattr(product, 'asin', '?')} "
        f"total={total:.1f} passed={passed}"
    )
    return ScoreBreakdown(
        profit_score=p_score,
        demand_score=d_score,
        competition_score=c_score,
        supply_score=s_score,
        logistics_score=l_score,
        risk_score=r_score,
        total_score=round(total, 2),
        passed_hard_filter=passed,
        rejection_reasons=reasons,
    )
