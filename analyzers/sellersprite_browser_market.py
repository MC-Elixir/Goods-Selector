"""Translate SellerSprite Reverse-ASIN browser evidence into market fields.

Only fields directly present in the normalized extension export are mapped.
Unknown market metrics remain ``None``; in particular reverse-keyword rows do
not prove estimated ASIN sales, market concentration, or seasonality.
"""
from __future__ import annotations

from math import isfinite
from typing import Any

from analyzers.maijiajingling import MarketAnalysisDTO


def market_from_reverse_keyword_result(
    *,
    asin: str,
    marketplace: str,
    result_data: dict[str, Any],
) -> MarketAnalysisDTO:
    """Build a conservative DTO from one successful browser-export result."""
    rows = result_data.get("keyword_rows")
    candidates = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    selected = _select_keyword_row(candidates)
    manifest_id = result_data.get("manifest_id")
    file_sha256 = result_data.get("file_sha256")
    row_count = result_data.get("row_count")

    dto = MarketAnalysisDTO(asin=asin, marketplace=marketplace)
    if selected is not None:
        dto.main_keyword = _text(selected.get("keyword"))
        dto.search_volume_monthly = _nonnegative_int(selected.get("search_volume"))
        dto.monthly_purchases = _nonnegative_int(selected.get("purchase_volume"))
        dto.purchase_rate = _nonnegative_number(selected.get("purchase_rate"))
        dto.competing_listings = _nonnegative_int(selected.get("competing_products"))
    dto.raw_data = {
        "source_provider": "sellersprite",
        "source_type": "browser_extension_export",
        "measurement_kind": "vendor_estimate",
        "manifest_id": manifest_id if isinstance(manifest_id, str) else None,
        "source_ref": f"sha256:{file_sha256}" if isinstance(file_sha256, str) else None,
        "row_count": row_count if isinstance(row_count, int) and not isinstance(row_count, bool) else None,
        "selected_keyword_row": _public_evidence_row(selected),
        # Keep a bounded, redacted keyword set so the supplier matcher can use
        # more than one Reverse-ASIN term.  Raw extension payloads and unknown
        # columns deliberately remain outside the market DTO.
        "keyword_candidates": [
            public
            for row in candidates[:20]
            if (public := _public_evidence_row(row)) is not None
        ],
        "missing_market_fields": [
            "est_daily_sales",
            "est_monthly_sales",
            "keyword_difficulty",
            "top10_revenue_share",
            "avg_review_count_top10",
            "avg_price_top10",
            "opportunity_score",
            "seasonality",
        ],
    }
    return dto


def _select_keyword_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    usable = [row for row in rows if _text(row.get("keyword"))]
    if not usable:
        return None
    # SellerSprite exports are normally traffic-ranked.  Search volume is the
    # strongest explicit metric when present; stable source order breaks ties.
    return max(
        enumerate(usable),
        key=lambda item: (
            _rank_number(item[1].get("search_volume")),
            _rank_number(item[1].get("purchase_volume")),
            -item[0],
        ),
    )[1]


def _public_evidence_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    fields = (
        "keyword",
        "search_volume",
        "purchase_volume",
        "purchase_rate",
        "competing_products",
        "spr",
        "organic_rank",
        "ad_rank",
    )
    return {field: row[field] for field in fields if field in row and row[field] is not None}


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _rank_number(value: object) -> float:
    number = _nonnegative_number(value)
    return number if number is not None else -1.0


def _nonnegative_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) and number >= 0 else None


def _nonnegative_int(value: object) -> int | None:
    number = _nonnegative_number(value)
    return int(number) if number is not None else None
