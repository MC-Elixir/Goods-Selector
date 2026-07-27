"""Persistence for seller-research shortlists produced by the market workflow."""
from __future__ import annotations

import json
from math import isfinite
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import Engine, inspect, text

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids import cycles at runtime
    from agent.tools.competitor_importer import ImportedCompetitorExport
    from analyzers.seller_research import SellerResearchItem, SellerShortlist


_RUN_COLUMNS = (
    "id, niche_label, keyword, marketplace, source_provider, source_type, "
    "source_file, file_sha256, observed_at, imported_at, row_count, "
    "eligible_count, excluded_count, ruleset_version, quality_summary_json, "
    "export_file, status"
)
_PUBLIC_RUN_COLUMNS = (
    "id, niche_label, keyword, marketplace, imported_at, row_count, "
    "eligible_count, excluded_count, ruleset_version, export_file, status"
)
_ITEM_COLUMNS = (
    "id, run_id, rank_index, seller, representative_asin, representative_title, "
    "brand, price, rating, review_count, launch_date, launch_months, "
    "monthly_sales, monthly_revenue, seller_product_count, product_count_source, "
    "fit_category, fit_category_label, fit_score, excluded, fit_factors_json, "
    "fit_reasons_json, exclusion_reasons_json, ai_reason"
)


def save_seller_research(
    engine: Engine,
    imported: "ImportedCompetitorExport",
    shortlist: "SellerShortlist",
    *,
    export_file: str | None = None,
) -> dict[str, Any]:
    """Persist one research run plus its ranked eligible and excluded items."""

    if imported.status != "imported":
        raise ValueError("competitor import status must be 'imported'")

    run_id = str(uuid4())
    run = {
        "id": run_id,
        "niche_label": imported.niche_label or (imported.keyword or "unknown"),
        "keyword": imported.keyword or None,
        "marketplace": imported.marketplace,
        "source_provider": imported.source_provider,
        "source_type": imported.source_type,
        "source_file": str(imported.artifact.path),
        "file_sha256": imported.artifact.sha256,
        "observed_at": imported.artifact.observed_at,
        "row_count": imported.row_count,
        "eligible_count": shortlist.eligible_count,
        "excluded_count": len(shortlist.excluded_items),
        "ruleset_version": shortlist.ruleset_version,
        "quality_summary_json": _dump_json(shortlist.quality_summary),
        "export_file": export_file,
        "status": "imported",
    }

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO seller_research_runs ("
                "id, niche_label, keyword, marketplace, source_provider, source_type, "
                "source_file, file_sha256, observed_at, row_count, eligible_count, "
                "excluded_count, ruleset_version, quality_summary_json, export_file, status"
                ") VALUES ("
                ":id, :niche_label, :keyword, :marketplace, :source_provider, :source_type, "
                ":source_file, :file_sha256, :observed_at, :row_count, :eligible_count, "
                ":excluded_count, :ruleset_version, :quality_summary_json, :export_file, :status"
                ")"
            ),
            run,
        )
        rank_index = 0
        for item in shortlist.items:
            connection.execute(_INSERT_ITEM, _item_params(run_id, rank_index, item))
            rank_index += 1
        for item in shortlist.excluded_items:
            connection.execute(_INSERT_ITEM, _item_params(run_id, rank_index, item))
            rank_index += 1

    saved = get_seller_research_run(engine, run_id)
    if saved is None:  # Defensive guard against a broken database driver.
        raise RuntimeError("failed to read saved seller research run")
    return saved


def get_seller_research_run(engine: Engine, run_id: str) -> dict[str, Any] | None:
    """Return one run's metadata with its ranked items decoded."""

    with engine.connect() as connection:
        if not _has_table(connection, "seller_research_runs"):
            return None
        run_row = connection.execute(
            text(f"SELECT {_RUN_COLUMNS} FROM seller_research_runs WHERE id=:id"),
            {"id": run_id},
        ).mappings().one_or_none()
        if run_row is None:
            return None
        item_rows = connection.execute(
            text(
                f"SELECT {_ITEM_COLUMNS} FROM seller_research_items "
                "WHERE run_id=:run_id ORDER BY rank_index ASC"
            ),
            {"run_id": run_id},
        ).mappings().all()

    run = _decode_run(dict(run_row))
    items = [_decode_item(dict(row)) for row in item_rows]
    run["items"] = [item for item in items if not item["excluded"]]
    run["excluded_items"] = [item for item in items if item["excluded"]]
    return run


def list_seller_research_runs(engine: Engine, *, limit: int = 20) -> list[dict[str, Any]]:
    """Return newest run metadata without the per-seller item payload."""
    safe_limit = max(1, min(int(limit), 50))
    with engine.connect() as connection:
        if not _has_table(connection, "seller_research_runs"):
            return []
        rows = connection.execute(
            text(
                f"SELECT {_PUBLIC_RUN_COLUMNS} FROM seller_research_runs "
                "ORDER BY imported_at DESC, id DESC LIMIT :limit"
            ),
            {"limit": safe_limit},
        ).mappings().all()
    return [dict(row) for row in rows]


_INSERT_ITEM = text(
    "INSERT INTO seller_research_items ("
    "id, run_id, rank_index, seller, representative_asin, representative_title, "
    "brand, price, rating, review_count, launch_date, launch_months, "
    "monthly_sales, monthly_revenue, seller_product_count, product_count_source, "
    "fit_category, fit_category_label, fit_score, excluded, fit_factors_json, "
    "fit_reasons_json, exclusion_reasons_json, ai_reason"
    ") VALUES ("
    ":id, :run_id, :rank_index, :seller, :representative_asin, :representative_title, "
    ":brand, :price, :rating, :review_count, :launch_date, :launch_months, "
    ":monthly_sales, :monthly_revenue, :seller_product_count, :product_count_source, "
    ":fit_category, :fit_category_label, :fit_score, :excluded, :fit_factors_json, "
    ":fit_reasons_json, :exclusion_reasons_json, :ai_reason"
    ")"
)


def _item_params(run_id: str, rank_index: int, item: "SellerResearchItem") -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "run_id": run_id,
        "rank_index": rank_index,
        "seller": item.seller,
        "representative_asin": item.representative_asin,
        "representative_title": item.representative_title,
        "brand": item.brand,
        "price": _finite(item.price),
        "rating": _finite(item.rating),
        "review_count": item.review_count,
        "launch_date": item.launch_date,
        "launch_months": _finite(item.launch_months),
        "monthly_sales": item.monthly_sales,
        "monthly_revenue": _finite(item.monthly_revenue),
        "seller_product_count": item.seller_product_count,
        "product_count_source": item.product_count_source,
        "fit_category": item.fit_category,
        "fit_category_label": item.fit_category_label,
        "fit_score": _finite(item.fit_score) or 0.0,
        "excluded": 1 if item.excluded else 0,
        "fit_factors_json": _dump_json(item.fit_factors),
        "fit_reasons_json": _dump_json(item.fit_reasons),
        "exclusion_reasons_json": _dump_json(item.exclusion_reasons),
        "ai_reason": item.ai_reason,
    }


def _decode_run(row: dict[str, Any]) -> dict[str, Any]:
    row["quality_summary"] = json.loads(row.pop("quality_summary_json"))
    return row


def _decode_item(row: dict[str, Any]) -> dict[str, Any]:
    row["fit_factors"] = json.loads(row.pop("fit_factors_json") or "{}")
    row["fit_reasons"] = json.loads(row.pop("fit_reasons_json") or "[]")
    row["exclusion_reasons"] = json.loads(row.pop("exclusion_reasons_json") or "[]")
    row["excluded"] = bool(row.get("excluded"))
    return row


def _has_table(connection: Any, table_name: str) -> bool:
    return inspect(connection).has_table(table_name)


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)) and isfinite(float(value)):
        return float(value)
    return None


def _dump_json(value: Any) -> str:
    return json.dumps(_json_safe(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
