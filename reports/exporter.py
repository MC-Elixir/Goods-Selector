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
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from config.settings import settings


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
        "通过筛选", "拒绝原因",
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
            "✓" if passed else "✗",
            ", ".join(sc.rejection_reasons) if sc else "",
        ]

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
                  8, 25]
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

        rejection_section = ""
        if sc and sc.rejection_reasons:
            rejection_section = (
                f"> ⚠️ 未通过硬性筛选：{', '.join(sc.rejection_reasons)}"
            )

        # 货源表格
        sup_lines = ["| # | 供应商 | 货源链接 | 采购价(CNY) | MOQ | 月销 | 回头率 |",
                     "|---|---|---|---|---|---|---|"]
        for i, s in enumerate(sups[:5], 1):
            sup_lines.append(
                f"| {i} | {getattr(s,'supplier_name','-')} "
                f"| [{getattr(s,'alibaba_offer_id','-')}]({getattr(s,'offer_url','#')}) "
                f"| {getattr(s,'base_price_cny','-')} "
                f"| {getattr(s,'moq','-')} "
                f"| {getattr(s,'monthly_sales','-')} "
                f"| {f\"{getattr(s,'repeat_buyer_rate',0):.0%}\" if getattr(s,'repeat_buyer_rate',None) else '-'} |"
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
        sups = rec.suppliers or []

        return {
            "product": {
                k: getattr(p, k, None)
                for k in ("asin", "marketplace", "title", "brand", "category",
                          "price", "bsr_rank", "rating", "review_count",
                          "weight_kg", "length_cm", "width_cm", "height_cm",
                          "main_image_url", "listing_url")
            },
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
            "suppliers": [
                {
                    k: getattr(s, k, None)
                    for k in ("alibaba_offer_id", "supplier_name", "offer_url",
                              "base_price_cny", "moq", "monthly_sales",
                              "repeat_buyer_rate", "is_factory", "delivery_days")
                }
                for s in sups[:10]
            ],
        }

    data = [_serialize(r) for r in candidates]
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"JSON 导出完成：{output_path}（{len(data)} 条）")
    return output_path
