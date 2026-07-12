"""
报告导出
========

输出三种产物：
    1. Excel 候选选品表    .xlsx，每行一个产品，含评分明细 + 利润明细
    2. Markdown 详情报告   每个产品一份 .md
    3. JSON                全量数据，便于下游消费

candidates 为 PipelineRecord 列表（见 pipeline/orchestrator.py）。
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from config.settings import settings


def _supplier_raw_score(supplier, key: str):
    raw = getattr(supplier, "raw_data", None) if supplier else None
    value = (raw or {}).get(key)
    return round(float(value), 3) if value is not None else None


def _display_score(value) -> str:
    return "-" if value is None else f"{value:.3f}"


def _record_rejection_reasons(record) -> list[str]:
    reasons = getattr(record, "rejection_reasons", None)
    if not reasons:
        score = getattr(record, "score", None)
        reasons = getattr(score, "rejection_reasons", None) or []
    recommendation = getattr(getattr(record, "sourcing_slice", None), "recommendation", None)
    evidence_reasons = getattr(recommendation, "rejection_reasons", None) or []
    return list(dict.fromkeys([*reasons, *evidence_reasons]))


def _record_review_status(record) -> str:
    reasons = _record_rejection_reasons(record)
    score = getattr(record, "score", None)
    if score is None and reasons:
        return "insufficient_evidence"
    if score is not None and getattr(score, "passed_hard_filter", False):
        return "passed"
    return "rejected"


def _evidence_payload(record) -> dict[str, Any]:
    slice_result = getattr(record, "sourcing_slice", None)
    recommendation = getattr(slice_result, "recommendation", None)
    status = getattr(recommendation, "status", None)
    status = getattr(status, "value", status)

    def _model(value):
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if is_dataclass(value):
            return asdict(value)
        return value

    matches = []
    if slice_result:
        evaluated = getattr(slice_result, "evaluated_matches", None)
        values = evaluated if evaluated is not None else [
            *getattr(slice_result, "accepted_matches", []),
            *getattr(slice_result, "rejected_matches", []),
        ]
        matches = [_model(item) for item in values]
    return {
        "schema_version": "2.0",
        "run_ref": getattr(slice_result, "run_ref", None),
        "query_plan_and_hit_rates": getattr(slice_result, "query_attempts", []),
        "match_evidence": matches,
        "recommendation_status": status,
        "recommendation_reasons": list(getattr(recommendation, "recommendation_reasons", []) or []),
        "evidence_rejection_reasons": list(getattr(recommendation, "rejection_reasons", []) or []),
        "manual_verification_tasks": list(getattr(recommendation, "manual_verification_tasks", []) or []),
    }


def _json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


# ============================================================
# Excel
# ============================================================

def export_excel(candidates: list, output_path: Optional[Path] = None) -> Path:
    """导出候选池为 Excel。每行一个产品，含评分维度 + 利润明细 + Top1 货源。"""
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise ImportError("请安装 openpyxl：pip install openpyxl")

    output_path = output_path or (
        settings.export_dir / f"candidates_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "候选选品"

    # --- 表头 ---
    headers = [
        "ASIN", "标题", "品牌", "类目",
        "售价($)", "BSR排名", "评分", "评论数",
        "综合评分", "利润率", "净利润($)",
        "利润得分", "需求得分", "竞争得分", "供应得分", "物流得分", "风险得分",
        "采购成本($)", "头程($)", "FBA费($)", "佣金($)", "广告费($)", "退货损耗($)",
        "供应商数", "Top1供应商", "Top1货源链接", "Top1采购价(CNY)", "Top1 MOQ",
        "Top1来源", "Top1视觉相似", "Top1匹配分", "Top1候选分", "Top1供应商质量分", "Top1业务条件分",
        "通过筛选", "审核状态", "拒绝原因",
        "Schema版本", "Run Ref", "查询计划与命中率", "匹配证据", "推荐状态",
        "推荐原因", "证据拒绝原因", "人工核验任务",
    ]

    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(color="FFFFFF", bold=True, size=10)

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # --- 数据行 ---
    green_fill = PatternFill("solid", fgColor="E2EFDA")
    red_fill = PatternFill("solid", fgColor="FFE7E7")

    for row_idx, rec in enumerate(candidates, 2):
        p = rec.product
        pb = rec.profit
        sc = rec.score
        sups = rec.suppliers or []
        top_sup = sups[0] if sups else None

        passed = sc.passed_hard_filter if sc else False
        row_fill = green_fill if passed else red_fill

        def _v(obj, attr, default=""):
            v = getattr(obj, attr, default)
            return v if v is not None else default

        def _score(obj, attr):
            value = getattr(obj, attr, None) if obj else None
            return round(float(value), 3) if value is not None else ""

        def _raw_score(obj, key):
            value = _supplier_raw_score(obj, key)
            return value if value is not None else ""

        row_data = [
            _v(p, "asin"),
            _v(p, "title"),
            _v(p, "brand"),
            _v(p, "category"),
            _v(p, "price"),
            _v(p, "bsr_rank"),
            _v(p, "rating"),
            _v(p, "review_count"),
            round(sc.total_score, 1) if sc else "",
            f"{pb.profit_margin:.1%}" if pb else "",
            round(pb.net_profit, 2) if pb else "",
            round(sc.profit_score, 3) if sc else "",
            round(sc.demand_score, 3) if sc else "",
            round(sc.competition_score, 3) if sc else "",
            round(sc.supply_score, 3) if sc else "",
            round(sc.logistics_score, 3) if sc else "",
            round(sc.risk_score, 3) if sc else "",
            round(pb.purchase_cost, 2) if pb else "",
            round(pb.shipping_cost, 2) if pb else "",
            round(pb.fba_fee, 2) if pb else "",
            round(pb.commission, 2) if pb else "",
            round(pb.ad_cost, 2) if pb else "",
            round(pb.return_loss, 2) if pb else "",
            len(sups),
            _v(top_sup, "supplier_name") if top_sup else "",
            _v(top_sup, "offer_url") if top_sup else "",
            _v(top_sup, "base_price_cny") if top_sup else "",
            _v(top_sup, "moq") if top_sup else "",
            _supplier_source(top_sup),
            _score(top_sup, "image_similarity"),
            _score(top_sup, "match_quality_score"),
            _raw_score(top_sup, "supplier_candidate_score"),
            _raw_score(top_sup, "supplier_quality_score"),
            _raw_score(top_sup, "supplier_business_score"),
            "✓" if passed else "✗",
            _record_review_status(rec),
            ", ".join(_record_rejection_reasons(rec)),
        ]
        evidence = _evidence_payload(rec)
        row_data.extend([
            evidence["schema_version"], evidence["run_ref"],
            _json_cell(evidence["query_plan_and_hit_rates"]),
            _json_cell(evidence["match_evidence"]), evidence["recommendation_status"],
            _json_cell(evidence["recommendation_reasons"]),
            _json_cell(evidence["evidence_rejection_reasons"]),
            _json_cell(evidence["manual_verification_tasks"]),
        ])

        for col, val in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col, value=val)
            cell.fill = row_fill
            cell.alignment = Alignment(vertical="center", wrap_text=False)

    # --- 列宽自适应 ---
    col_widths = [12, 40, 15, 20, 8, 10, 6, 8,
                  10, 8, 10,
                  10, 10, 10, 10, 10, 10,
                  10, 8, 8, 8, 8, 10,
                  8, 25, 40, 12, 8,
                  12, 10, 10, 10, 12, 12,
                  8, 24, 25]
    col_widths.extend([12, 18, 35, 35, 24, 30, 30, 30])
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    wb.save(output_path)
    logger.info(f"Excel 导出完成：{output_path}（{len(candidates)} 行）")
    return output_path


# ============================================================
# Markdown
# ============================================================

_MD_TEMPLATE = """\
# {title}

> ASIN: `{asin}` | 类目: {category} | 综合评分: **{total_score}** | {passed_badge}

---

## 基本信息

| 字段 | 值 |
|---|---|
| 售价 | ${price} |
| BSR 排名 | {bsr_rank} |
| 评分 / 评论数 | {rating} / {review_count} |
| 品牌 | {brand} |
| Listing | {listing_url} |

{image_section}

---

## 评分明细

| 维度 | 得分（0-1） | 权重 |
|---|---|---|
| 利润率 | {profit_score} | 20% |
| 市场需求 | {demand_score} | 25% |
| 竞争烈度 | {competition_score} | 20% |
| 货源稳定性 | {supply_score} | 15% |
| 物流友好度 | {logistics_score} | 10% |
| 风险等级 | {risk_score} | 10% |
| **综合** | **{total_score}** | — |

{rejection_section}

---

## 利润明细

| 费项 | 金额(USD) |
|---|---|
| 售价 | ${selling_price:.2f} |
| 采购成本 | -${purchase_cost:.2f} |
| 头程物流 | -${shipping_cost:.2f} |
| FBA 费用 | -${fba_fee:.2f} |
| 平台佣金 | -${commission:.2f} |
| 广告费 | -${ad_cost:.2f} |
| 退货损耗 | -${return_loss:.2f} |
| 汇率损耗 | -${exchange_loss:.2f} |
| **净利润** | **${net_profit:.2f}** |
| **净利率** | **{profit_margin:.1%}** |

---

## 推荐货源（Top {sup_count}）

{suppliers_section}

---

*生成时间：{generated_at}*
"""


def export_markdown(candidates: list, output_dir: Optional[Path] = None) -> list[Path]:
    """每个候选产品导出一份 .md 报告。"""
    output_dir = output_dir or settings.export_dir / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for rec in candidates:
        p = rec.product
        pb = rec.profit
        sc = rec.score
        sups = rec.suppliers or []

        asin = getattr(p, "asin", "unknown")
        img_url = getattr(p, "main_image_url", None)
        image_section = f"![{asin}]({img_url})" if img_url else ""

        rejection_section = f"> 审核状态：{_record_review_status(rec)}"
        rejection_reasons = _record_rejection_reasons(rec)
        if rejection_reasons:
            rejection_section = (
                f"> 审核状态：{_record_review_status(rec)}\n> ⚠️ 未通过硬性筛选：{', '.join(rejection_reasons)}"
            )

        # 货源表格
        sup_lines = [
            "| # | 来源 | 供应商 | 货源链接 | 采购价(CNY) | MOQ | 月销 | 回头率 | 匹配分 | 候选分 | 供应商质量分 |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for i, s in enumerate(sups[:5], 1):
            sup_lines.append(
                f"| {i} | {_supplier_source(s)} "
                f"| {getattr(s,'supplier_name','-')} "
                f"| [{getattr(s,'alibaba_offer_id','-')}]({getattr(s,'offer_url','#')}) "
                f"| {getattr(s,'base_price_cny','-')} "
                f"| {getattr(s,'moq','-')} "
                f"| {getattr(s,'monthly_sales','-')} "
                f"| {getattr(s,'repeat_buyer_rate','-')} "
                f"| {_display_score(getattr(s,'match_quality_score', None))} "
                f"| {_display_score(_supplier_raw_score(s, 'supplier_candidate_score'))} "
                f"| {_display_score(_supplier_raw_score(s, 'supplier_quality_score'))} |"
            )

        content = _MD_TEMPLATE.format(
            title=getattr(p, "title", asin),
            asin=asin,
            category=getattr(p, "category", "-"),
            total_score=round(sc.total_score, 1) if sc else "-",
            passed_badge="✅ 通过筛选" if (sc and sc.passed_hard_filter) else "❌ 未通过筛选",
            price=getattr(p, "price", "-"),
            bsr_rank=getattr(p, "bsr_rank", "-"),
            rating=getattr(p, "rating", "-"),
            review_count=getattr(p, "review_count", "-"),
            brand=getattr(p, "brand", "-"),
            listing_url=getattr(p, "listing_url", "#"),
            image_section=image_section,
            profit_score=round(sc.profit_score, 3) if sc else "-",
            demand_score=round(sc.demand_score, 3) if sc else "-",
            competition_score=round(sc.competition_score, 3) if sc else "-",
            supply_score=round(sc.supply_score, 3) if sc else "-",
            logistics_score=round(sc.logistics_score, 3) if sc else "-",
            risk_score=round(sc.risk_score, 3) if sc else "-",
            rejection_section=rejection_section,
            selling_price=pb.selling_price if pb else 0,
            purchase_cost=pb.purchase_cost if pb else 0,
            shipping_cost=pb.shipping_cost if pb else 0,
            fba_fee=pb.fba_fee if pb else 0,
            commission=pb.commission if pb else 0,
            ad_cost=pb.ad_cost if pb else 0,
            return_loss=pb.return_loss if pb else 0,
            exchange_loss=pb.exchange_loss if pb else 0,
            net_profit=pb.net_profit if pb else 0,
            profit_margin=pb.profit_margin if pb else 0,
            sup_count=min(len(sups), 5),
            suppliers_section="\n".join(sup_lines),
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
        evidence = _evidence_payload(rec)
        evidence_section = (
            "\n## 证据链\n\n"
            f"- Schema version: `{evidence['schema_version']}`\n"
            f"- Run ref: `{evidence['run_ref'] or '-'}`\n"
            f"- Recommendation status: `{evidence['recommendation_status'] or '-'}`\n"
            f"- Query plan and hit rates: `{_json_cell(evidence['query_plan_and_hit_rates'])}`\n"
            f"- Match evidence: `{_json_cell(evidence['match_evidence'])}`\n"
            f"- Recommendation reasons: `{_json_cell(evidence['recommendation_reasons'])}`\n"
            f"- Rejection reasons: `{_json_cell(evidence['evidence_rejection_reasons'])}`\n"
            f"- Manual verification tasks: `{_json_cell(evidence['manual_verification_tasks'])}`\n\n"
        )
        content = content.replace("\n---\n\n*生成时间", f"{evidence_section}\n---\n\n*生成时间")

        out = output_dir / f"{asin}.md"
        out.write_text(content, encoding="utf-8")
        paths.append(out)

    logger.info(f"Markdown 导出完成：{len(paths)} 份报告 → {output_dir}")
    return paths


# ============================================================
# JSON
# ============================================================

def export_json(candidates: list, output_path: Optional[Path] = None) -> Path:
    """导出全量数据为 JSON，供下游程序消费。"""
    output_path = output_path or (
        settings.export_dir / f"candidates_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

    def _serialize(rec) -> dict:
        p = rec.product
        pb = rec.profit
        sc = rec.score
        market = getattr(rec, "market", None)
        sups = rec.suppliers or []
        raw = getattr(p, "raw_data", None) if p else None
        raw = raw if isinstance(raw, dict) else {}

        payload = {
            "review_status": _record_review_status(rec),
            "rejection_reasons": _record_rejection_reasons(rec),
            "product": {
                k: getattr(p, k, None)
                for k in ("asin", "marketplace", "title", "brand", "category",
                          "price", "bsr_rank", "rating", "review_count",
                          "weight_kg", "length_cm", "width_cm", "height_cm",
                          "main_image_url", "listing_url")
            },
            "source_mode": raw.get("source_mode"),
            "source_query": raw.get("source_query") or raw.get("source_keyword") or raw.get("source_category"),
            "source_keyword": raw.get("source_keyword"),
            "keyword_normalized": raw.get("keyword_normalized"),
            "source_rank": raw.get("source_rank"),
            "source_warning": raw.get("keyword_warning"),
            "profit": {
                "selling_price": pb.selling_price,
                "purchase_cost": pb.purchase_cost,
                "shipping_cost": pb.shipping_cost,
                "fba_fee": pb.fba_fee,
                "commission": pb.commission,
                "ad_cost": pb.ad_cost,
                "return_loss": pb.return_loss,
                "exchange_loss": pb.exchange_loss,
                "net_profit": round(pb.net_profit, 4),
                "profit_margin": round(pb.profit_margin, 4),
            } if pb else None,
            "score": {
                "total_score": sc.total_score,
                "profit_score": sc.profit_score,
                "demand_score": sc.demand_score,
                "competition_score": sc.competition_score,
                "supply_score": sc.supply_score,
                "logistics_score": sc.logistics_score,
                "risk_score": sc.risk_score,
                "passed_hard_filter": sc.passed_hard_filter,
                "rejection_reasons": sc.rejection_reasons,
            } if sc else None,
            "market": _market_payload(market),
            "suppliers": [_supplier_payload(s) for s in sups[:10]],
        }
        payload.update(_evidence_payload(rec))
        return payload

    data = [_serialize(r) for r in candidates]
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"JSON 导出完成：{output_path}（{len(data)} 条）")
    return output_path


def _supplier_payload(supplier) -> dict[str, Any]:
    payload = {
        k: getattr(supplier, k, None)
        for k in ("alibaba_offer_id", "supplier_name", "offer_url",
                  "base_price_cny", "moq", "monthly_sales",
                  "repeat_buyer_rate", "is_factory", "delivery_days",
                  "title_cn", "offer_image_url", "image_similarity",
                  "match_quality_score",
                  "match_verification_method", "raw_data")
    }
    payload["supplier_quality_score"] = _supplier_raw_score(supplier, "supplier_quality_score")
    payload["supplier_business_score"] = _supplier_raw_score(supplier, "supplier_business_score")
    payload["candidate_score"] = _supplier_raw_score(supplier, "supplier_candidate_score")
    payload["sourcing_source"] = _supplier_source(supplier)
    payload["invalid_for_decision"] = _supplier_invalid_for_decision(supplier)
    return payload


def _supplier_source(supplier) -> str:
    if not supplier:
        return ""
    raw = getattr(supplier, "raw_data", None) or {}
    source = getattr(supplier, "sourcing_source", None) or raw.get("source")
    if source:
        return str(source)
    method = str(getattr(supplier, "match_verification_method", "") or "").lower()
    if method == "mock":
        return "mock"
    return "unknown"


def _supplier_invalid_for_decision(supplier) -> bool:
    if not supplier:
        return False
    raw = getattr(supplier, "raw_data", None) or {}
    source = _supplier_source(supplier).lower()
    method = str(getattr(supplier, "match_verification_method", "") or "").lower()
    name = str(getattr(supplier, "supplier_name", "") or "").lower()
    offer_id = str(getattr(supplier, "alibaba_offer_id", "") or "")
    return bool(
        raw.get("invalid_for_decision")
        or source == "mock"
        or method == "mock"
        or "mock" in name
        or (offer_id and not offer_id.isdigit())
    )


def _market_payload(market) -> dict[str, Any] | None:
    if not market:
        return None
    if is_dataclass(market):
        data = asdict(market)
    else:
        keys = (
            "asin", "marketplace", "brand", "seller_name", "title",
            "bsr", "bsr_category", "est_daily_sales", "est_monthly_sales",
            "price", "currency", "rating", "review_count", "available_date",
            "has_a_plus", "is_best_seller", "is_amazon_choice",
            "competing_listings", "avg_price_top10", "avg_review_count_top10",
            "top10_revenue_share", "main_keyword", "search_volume_monthly",
            "monthly_purchases", "purchase_rate", "keyword_difficulty",
            "opportunity_score", "seasonality", "raw_data",
        )
        data = {key: getattr(market, key, None) for key in keys}
    available = data.get("available_date")
    if isinstance(available, datetime):
        data["available_date"] = available.isoformat()
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}
