"""Read exported candidate files and maintain saved selections."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from config.settings import DATA_DIR, settings
from agent.review_decisions import load_supplier_reviews, supplier_review_key
from matchers.product_spec import spec_from_product, spec_from_supplier

_SAVED_FILE = DATA_DIR / "agent_saved_items.json"
_HIDDEN_FILE = DATA_DIR / "agent_hidden_items.json"


def list_export_runs(limit: int = 30) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for path in sorted(settings.export_dir.glob("candidates_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        rows = _read_json_list(path)
        stem = path.stem.replace("candidates_", "")
        xlsx = path.with_suffix(".xlsx")
        run = {
            "id": stem,
            "json_file": path.name,
            "xlsx_file": xlsx.name if xlsx.exists() else None,
            "created_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            "count": len(rows),
            "mock_count": _count_mock(rows),
            "avg_score": _avg_score(rows),
            "top_margin": _top_margin(rows),
        }
        run.update(_audit_rows(rows, compact=True))
        runs.append(run)
        if len(runs) >= limit:
            break
    return runs


def list_results(run_id: str | None = None, limit: int = 200) -> dict[str, Any]:
    saved = _load_saved()
    hidden = _load_hidden()
    supplier_reviews = load_supplier_reviews()
    files = _matching_files(run_id)
    items: list[dict[str, Any]] = []
    for path in files:
        rows = _read_json_list(path)
        export_id = path.stem.replace("candidates_", "")
        xlsx = path.with_suffix(".xlsx")
        for row in rows:
            product = row.get("product") or {}
            profit = row.get("profit") or {}
            score = row.get("score") or {}
            market = row.get("market") or {}
            suppliers = row.get("suppliers") or []
            top_supplier = suppliers[0] if suppliers else {}
            spec_match = (top_supplier.get("raw_data") or {}).get("spec_match") or {}
            product_spec = _target_spec(top_supplier) or _product_spec(product)
            top_supplier_spec = _supplier_spec(top_supplier) if top_supplier else {}
            invalid_for_decision = bool(top_supplier.get("invalid_for_decision")) or _supplier_is_mock(top_supplier)
            key = f"{export_id}:{product.get('asin', '')}"
            if key in hidden:
                continue
            item = {
                "key": key,
                "export_id": export_id,
                "source_mode": row.get("source_mode") or (product.get("raw_data") or {}).get("source_mode"),
                "source_query": row.get("source_query") or (product.get("raw_data") or {}).get("source_query"),
                "source_keyword": row.get("source_keyword") or (product.get("raw_data") or {}).get("source_keyword"),
                "keyword_normalized": row.get("keyword_normalized") or (product.get("raw_data") or {}).get("keyword_normalized"),
                "source_rank": row.get("source_rank") or (product.get("raw_data") or {}).get("source_rank"),
                "asin": product.get("asin"),
                "title": product.get("title"),
                "brand": product.get("brand"),
                "category": product.get("category"),
                "price": product.get("price"),
                "image": product.get("main_image_url"),
                "amazon_url": product.get("amazon_url") or _amazon_url(product),
                "supplier": top_supplier.get("supplier_name"),
                "offer_url": top_supplier.get("offer_url"),
                "buy_cost_cny": top_supplier.get("base_price_cny"),
                "moq": top_supplier.get("moq"),
                "margin": profit.get("profit_margin"),
                "net_profit": profit.get("net_profit"),
                "score": score.get("total_score"),
                "passed": score.get("passed_hard_filter"),
                "score_breakdown": _score_breakdown(score),
                "rejection_reasons": score.get("rejection_reasons") or [],
                "profit_breakdown": _profit_breakdown(profit),
                "market": _market_summary(market),
                "mock": _supplier_is_mock(top_supplier),
                "invalid_for_decision": invalid_for_decision,
                "match_quality": top_supplier.get("match_quality_score"),
                "visual_similarity": top_supplier.get("image_similarity"),
                "visual_match": ((top_supplier.get("raw_data") or {}).get("visual_match") or {}),
                "spec_match_score": spec_match.get("score"),
                "spec_match_matched": spec_match.get("matched") or [],
                "spec_match_missing": spec_match.get("missing") or [],
                "spec_match_conflicts": spec_match.get("conflicts") or [],
                "product_spec": product_spec,
                "top_supplier_spec": top_supplier_spec,
                "spec_comparison": _spec_comparison(product_spec, top_supplier_spec, spec_match),
                "supplier_candidates": _supplier_candidates(suppliers, key, supplier_reviews),
                "supplier_review_summary": _supplier_review_summary(suppliers, key, supplier_reviews),
                "review_status": _review_status(spec_match, top_supplier, score),
                "review_summary": _review_summary(spec_match, top_supplier),
                "decision_brief": _decision_brief(score, profit, market, top_supplier, spec_match),
                "saved": key in saved,
                "xlsx_file": xlsx.name if xlsx.exists() else None,
            }
            items.append(item)
            if len(items) >= limit:
                return {"items": items, "count": len(items)}
    return {"items": items, "count": len(items)}


def list_accepted_supplier_shortlist(run_id: str | None = None, limit: int = 500) -> dict[str, Any]:
    decisions = load_supplier_reviews()
    files = _matching_files(run_id)
    items: list[dict[str, Any]] = []
    for path in files:
        rows = _read_json_list(path)
        export_id = path.stem.replace("candidates_", "")
        for row in rows:
            product = row.get("product") or {}
            profit = row.get("profit") or {}
            score = row.get("score") or {}
            suppliers = row.get("suppliers") or []
            product_key = f"{export_id}:{product.get('asin', '')}"
            for idx, supplier in enumerate(suppliers[:5], 1):
                review_key = supplier_review_key(product_key, supplier, idx)
                decision = decisions.get(review_key) or {}
                if decision.get("status") != "accepted":
                    continue
                raw = supplier.get("raw_data") or {}
                spec_match = raw.get("spec_match") or {}
                items.append({
                    "review_key": review_key,
                    "reviewed_at": decision.get("reviewed_at"),
                    "export_id": export_id,
                    "asin": product.get("asin"),
                    "product_title": product.get("title"),
                    "product_price": product.get("price"),
                    "total_score": score.get("total_score"),
                    "profit_margin": profit.get("profit_margin"),
                    "net_profit": profit.get("net_profit"),
                    "supplier_rank": idx,
                    "supplier": supplier.get("supplier_name"),
                    "supplier_title": supplier.get("title_cn") or raw.get("title_cn"),
                    "offer_url": supplier.get("offer_url"),
                    "offer_image_url": supplier.get("offer_image_url"),
                    "price_cny": supplier.get("base_price_cny"),
                    "moq": supplier.get("moq"),
                    "monthly_sales": supplier.get("monthly_sales"),
                    "repeat_buyer_rate": supplier.get("repeat_buyer_rate"),
                    "is_factory": supplier.get("is_factory"),
                    "sourcing_source": _supplier_source(supplier),
                    "match_quality": supplier.get("match_quality_score"),
                    "visual_similarity": supplier.get("image_similarity"),
                    "supplier_quality_score": supplier.get("supplier_quality_score", raw.get("supplier_quality_score")),
                    "supplier_business_score": supplier.get("supplier_business_score", raw.get("supplier_business_score")),
                    "candidate_score": supplier.get("candidate_score", raw.get("supplier_candidate_score")),
                    "spec_match_score": spec_match.get("score"),
                    "spec_conflicts": ", ".join(spec_match.get("conflicts") or []),
                    "spec_missing": ", ".join(spec_match.get("missing") or []),
                    "note": decision.get("note") or "",
                })
                if len(items) >= limit:
                    return {"items": items, "count": len(items)}
    return {"items": items, "count": len(items)}


def set_saved(key: str, saved: bool) -> dict[str, Any]:
    data = _load_saved()
    if saved:
        data[key] = {"saved_at": datetime.utcnow().isoformat()}
    else:
        data.pop(key, None)
    _SAVED_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SAVED_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"key": key, "saved": saved, "saved_count": len(data)}


def hide_result(key: str) -> dict[str, Any]:
    value = (key or "").strip()
    if ":" not in value or value.startswith(":") or value.endswith(":"):
        raise ValueError("invalid result key")
    hidden = _load_hidden()
    hidden[value] = {"hidden_at": datetime.utcnow().isoformat()}
    _HIDDEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _HIDDEN_FILE.write_text(json.dumps(hidden, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"key": value, "hidden": True, "hidden_count": len(hidden)}


def audit_export(path: Path) -> dict[str, Any]:
    rows = _read_json_list(path)
    margins = [
        (row.get("profit") or {}).get("profit_margin")
        for row in rows
        if (row.get("profit") or {}).get("profit_margin") is not None
    ]
    suspicious_price = []
    for row in rows:
        suppliers = row.get("suppliers") or []
        top = suppliers[0] if suppliers else {}
        cost = top.get("base_price_cny")
        if isinstance(cost, (int, float)) and (cost < 1 or cost > 5000):
            suspicious_price.append((row.get("product") or {}).get("asin"))
    audit = {
        "candidate_count": len(rows),
        "avg_margin": round(sum(margins) / len(margins), 4) if margins else None,
        "suspicious_price_count": len(suspicious_price),
        "suspicious_price_asins": suspicious_price[:20],
    }
    audit.update(_audit_rows(rows))
    return audit


def latest_export_after(timestamp: float) -> dict[str, Path]:
    files = [p for p in settings.export_dir.glob("candidates_*.json") if p.stat().st_mtime >= timestamp]
    if not files:
        return {}
    json_path = max(files, key=lambda p: p.stat().st_mtime)
    xlsx_path = json_path.with_suffix(".xlsx")
    return {
        "json": json_path,
        "xlsx": xlsx_path if xlsx_path.exists() else None,
    }


def _matching_files(run_id: str | None) -> list[Path]:
    if run_id:
        path = settings.export_dir / f"candidates_{run_id}.json"
        return [path] if path.exists() else []
    return sorted(settings.export_dir.glob("candidates_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _load_saved() -> dict[str, Any]:
    if not _SAVED_FILE.exists():
        return {}
    try:
        data = json.loads(_SAVED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_hidden() -> dict[str, Any]:
    if not _HIDDEN_FILE.exists():
        return {}
    try:
        data = json.loads(_HIDDEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _product_spec(product: dict[str, Any]) -> dict[str, Any]:
    return _compact_spec(asdict(spec_from_product(SimpleNamespace(**product))))


def _target_spec(supplier: dict[str, Any]) -> dict[str, Any]:
    raw = supplier.get("raw_data") or {}
    target = raw.get("target_spec")
    return _compact_spec(dict(target)) if isinstance(target, dict) else {}


def _supplier_spec(supplier: dict[str, Any]) -> dict[str, Any]:
    data = dict(supplier)
    data["raw_data"] = supplier.get("raw_data") or {}
    return _compact_spec(asdict(spec_from_supplier(SimpleNamespace(**data))))


def _compact_spec(spec: dict[str, Any]) -> dict[str, Any]:
    spec.pop("raw_text", None)
    return {k: v for k, v in spec.items() if v not in (None, "", [], {})}


def _spec_comparison(
    product_spec: dict[str, Any],
    supplier_spec: dict[str, Any],
    spec_match: dict[str, Any],
) -> list[dict[str, Any]]:
    field_map = [
        ("category", "category"),
        ("material", "material"),
        ("capacity", "capacity_ml"),
        ("pack_count", "pack_count"),
        ("dimensions", "dimensions_cm"),
        ("weight", "weight_g"),
        ("color", "color"),
        ("features", "features"),
        ("risk_flags", "risk_flags"),
    ]
    matched = set(spec_match.get("matched") or [])
    missing = set(spec_match.get("missing") or [])
    conflicts = set(spec_match.get("conflicts") or [])
    rows: list[dict[str, Any]] = []
    for match_key, spec_key in field_map:
        target = product_spec.get(spec_key)
        supplier = supplier_spec.get(spec_key)
        has_match_signal = match_key in matched or match_key in missing or match_key in conflicts
        if target in (None, "", [], {}) and supplier in (None, "", [], {}) and not has_match_signal:
            continue
        status = "unknown"
        if match_key in conflicts:
            status = "conflict"
        elif match_key in missing:
            status = "missing"
        elif match_key in matched:
            status = "matched"
        rows.append({
            "field": spec_key,
            "match_key": match_key,
            "target": target,
            "supplier": supplier,
            "status": status,
        })
    return rows


def _market_summary(market: dict[str, Any]) -> dict[str, Any]:
    if not market:
        return {}
    keys = (
        "bsr", "bsr_category", "est_daily_sales", "est_monthly_sales",
        "competing_listings", "avg_price_top10", "avg_review_count_top10",
        "top10_revenue_share", "main_keyword", "search_volume_monthly",
        "monthly_purchases", "purchase_rate", "keyword_difficulty",
        "opportunity_score", "seasonality",
    )
    return {key: market.get(key) for key in keys if market.get(key) not in (None, "", [], {})}


def _score_breakdown(score: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "profit_score", "demand_score", "competition_score",
        "supply_score", "logistics_score", "risk_score", "total_score",
    )
    return {key: score.get(key) for key in keys if score.get(key) is not None}


def _profit_breakdown(profit: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "selling_price", "purchase_cost", "shipping_cost", "fba_fee",
        "commission", "ad_cost", "return_loss", "exchange_loss",
        "net_profit", "profit_margin",
    )
    return {key: profit.get(key) for key in keys if profit.get(key) is not None}


def _supplier_candidates(
    suppliers: list[dict[str, Any]],
    product_key: str,
    decisions: dict[str, Any],
    limit: int = 5,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for idx, supplier in enumerate(suppliers[:limit], 1):
        raw = supplier.get("raw_data") or {}
        spec_match = raw.get("spec_match") or {}
        review_key = supplier_review_key(product_key, supplier, idx)
        decision = decisions.get(review_key) or {}
        candidates.append({
            "rank": idx,
            "review_key": review_key,
            "review_status": decision.get("status") or "pending",
            "review_note": decision.get("note") or "",
            "alibaba_offer_id": supplier.get("alibaba_offer_id"),
            "supplier": supplier.get("supplier_name"),
            "title": supplier.get("title_cn") or raw.get("title_cn"),
            "offer_url": supplier.get("offer_url"),
            "offer_image_url": supplier.get("offer_image_url"),
            "price_cny": supplier.get("base_price_cny"),
            "moq": supplier.get("moq"),
            "monthly_sales": supplier.get("monthly_sales"),
            "repeat_buyer_rate": supplier.get("repeat_buyer_rate"),
            "is_factory": supplier.get("is_factory"),
            "sourcing_source": _supplier_source(supplier),
            "match_quality": supplier.get("match_quality_score"),
            "visual_similarity": supplier.get("image_similarity"),
            "supplier_quality_score": supplier.get("supplier_quality_score", raw.get("supplier_quality_score")),
            "supplier_business_score": supplier.get("supplier_business_score", raw.get("supplier_business_score")),
            "candidate_score": supplier.get("candidate_score", raw.get("supplier_candidate_score")),
            "rank_score": raw.get("supplier_rank_score"),
            "profit_margin": raw.get("supplier_profit_margin"),
            "net_profit": raw.get("supplier_net_profit"),
            "purchase_cost_usd": raw.get("supplier_purchase_cost"),
            "profit_score": raw.get("supplier_profit_score"),
            "visual_match": raw.get("visual_match") or {},
            "verification_method": supplier.get("match_verification_method"),
            "spec_match": {
                "score": spec_match.get("score"),
                "matched": spec_match.get("matched") or [],
                "missing": spec_match.get("missing") or [],
                "conflicts": spec_match.get("conflicts") or [],
            },
            "supplier_spec": _supplier_spec(supplier),
        })
    return candidates


def _supplier_review_summary(
    suppliers: list[dict[str, Any]],
    product_key: str,
    decisions: dict[str, Any],
) -> dict[str, int]:
    summary = {"accepted": 0, "rejected": 0, "pending": 0}
    for idx, supplier in enumerate(suppliers[:5], 1):
        decision = decisions.get(supplier_review_key(product_key, supplier, idx)) or {}
        status = decision.get("status") or "pending"
        if status in summary:
            summary[status] += 1
    return summary


def _supplier_source(supplier: dict[str, Any]) -> str:
    raw = supplier.get("raw_data") or {}
    source = supplier.get("sourcing_source") or raw.get("source")
    if source:
        return str(source)
    method = str(supplier.get("match_verification_method") or "").lower()
    if method == "mock":
        return "mock"
    return "unknown"


def _audit_rows(rows: list[dict[str, Any]], compact: bool = False) -> dict[str, Any]:
    mock_count = _count_mock(rows)
    statuses: dict[str, int] = {
        "ready": 0,
        "needs_specs": 0,
        "conflict": 0,
        "no_supplier": 0,
        "review": 0,
    }
    spec_scores: list[float] = []
    match_quality_scores: list[float] = []
    supplier_counts: list[int] = []
    market_data_count = 0
    market_data_rich_count = 0
    manual_count = 0
    total_issues = 0
    supplier_source_counts: dict[str, int] = {}
    supplier_evidence_count = 0

    for row in rows:
        suppliers = row.get("suppliers") or []
        top_supplier = suppliers[0] if suppliers else {}
        score = row.get("score") or {}
        market = row.get("market") or {}
        spec_match = (top_supplier.get("raw_data") or {}).get("spec_match") or {}
        status = _review_status(spec_match, top_supplier, score)
        statuses[status] = statuses.get(status, 0) + 1
        if status != "ready":
            manual_count += 1
        total_issues += len(spec_match.get("missing") or []) + len(spec_match.get("conflicts") or [])
        supplier_counts.append(len(suppliers))
        if isinstance(spec_match.get("score"), (int, float)):
            spec_scores.append(float(spec_match["score"]))
        if isinstance(top_supplier.get("match_quality_score"), (int, float)):
            match_quality_scores.append(float(top_supplier["match_quality_score"]))
        source = _supplier_source(top_supplier) if top_supplier else "none"
        supplier_source_counts[source] = supplier_source_counts.get(source, 0) + 1
        if _has_supplier_evidence(top_supplier):
            supplier_evidence_count += 1
        if _has_market_evidence(market):
            market_data_count += 1
        if _has_rich_market_evidence(market):
            market_data_rich_count += 1

    count = len(rows)
    ready_count = statuses.get("ready", 0)
    real_supplier_count = sum(
        1 for row in rows
        if (row.get("suppliers") or []) and not _supplier_is_mock((row.get("suppliers") or [])[0])
    )
    quality = _sourcing_quality(count, mock_count, statuses)
    data = {
        "mock_count": mock_count,
        "real_supplier_count": real_supplier_count,
        "supplier_evidence_count": supplier_evidence_count,
        "supplier_evidence_rate": round(supplier_evidence_count / count, 4) if count else 0.0,
        "supplier_evidence_ready": supplier_evidence_count == count and count > 0,
        "supplier_source_counts": supplier_source_counts,
        "sourcing_quality": quality,
        "review_ready_count": ready_count,
        "review_manual_count": manual_count,
        "review_conflict_count": statuses.get("conflict", 0),
        "review_needs_specs_count": statuses.get("needs_specs", 0),
        "review_no_supplier_count": statuses.get("no_supplier", 0),
        "review_ready_rate": round(ready_count / count, 4) if count else 0.0,
        "market_data_count": market_data_count,
        "market_data_rate": round(market_data_count / count, 4) if count else 0.0,
        "market_data_ready": market_data_count == count and count > 0,
        "market_data_rich_count": market_data_rich_count,
        "market_data_rich_rate": round(market_data_rich_count / count, 4) if count else 0.0,
        "market_data_rich_ready": market_data_rich_count == count and count > 0,
        "avg_spec_match_score": _avg(spec_scores),
        "avg_match_quality_score": _avg(match_quality_scores),
        "avg_supplier_candidates": _avg([float(v) for v in supplier_counts]),
        "total_spec_issues": total_issues,
    }
    if compact:
        return {
            "sourcing_quality": data["sourcing_quality"],
            "review_ready_count": data["review_ready_count"],
            "review_manual_count": data["review_manual_count"],
            "review_conflict_count": data["review_conflict_count"],
            "review_ready_rate": data["review_ready_rate"],
            "supplier_evidence_count": data["supplier_evidence_count"],
            "supplier_evidence_rate": data["supplier_evidence_rate"],
            "market_data_count": data["market_data_count"],
            "market_data_rate": data["market_data_rate"],
            "market_data_rich_count": data["market_data_rich_count"],
            "market_data_rich_rate": data["market_data_rich_rate"],
            "avg_spec_match_score": data["avg_spec_match_score"],
        }
    return data


def _has_supplier_evidence(supplier: dict[str, Any]) -> bool:
    if not supplier or _supplier_is_mock(supplier):
        return False
    raw = supplier.get("raw_data") or {}
    spec_match = raw.get("spec_match") or {}
    has_identity = any(
        supplier.get(key) not in (None, "", [], {})
        for key in ("alibaba_offer_id", "supplier_name", "title_cn", "offer_url")
    )
    has_match = (
        isinstance(supplier.get("match_quality_score"), (int, float))
        or isinstance(spec_match.get("score"), (int, float))
        or bool(spec_match.get("matched") or spec_match.get("missing") or spec_match.get("conflicts"))
    )
    return bool(has_identity and has_match)


def _has_market_evidence(market: dict[str, Any]) -> bool:
    if not market:
        return False
    evidence_keys = (
        "bsr", "est_daily_sales", "est_monthly_sales", "competing_listings",
        "avg_price_top10", "avg_review_count_top10", "top10_revenue_share",
        "main_keyword", "search_volume_monthly", "monthly_purchases",
        "purchase_rate", "keyword_difficulty", "opportunity_score",
    )
    return any(market.get(key) not in (None, "", [], {}) for key in evidence_keys)


def _has_rich_market_evidence(market: dict[str, Any]) -> bool:
    if not _has_market_evidence(market):
        return False
    rich_keys = (
        "est_daily_sales", "est_monthly_sales", "competing_listings",
        "avg_review_count_top10", "top10_revenue_share",
        "search_volume_monthly", "monthly_purchases", "opportunity_score",
    )
    return any(market.get(key) not in (None, "", [], {}) for key in rich_keys)


def _sourcing_quality(count: int, mock_count: int, statuses: dict[str, int]) -> str:
    if count == 0 or statuses.get("no_supplier", 0) == count:
        return "blocked"
    if mock_count:
        return "mock_review"
    if statuses.get("conflict", 0):
        return "conflict_review"
    ready_rate = statuses.get("ready", 0) / count
    if ready_rate >= 0.7:
        return "ready"
    return "needs_review"


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _review_status(spec_match: dict[str, Any], supplier: dict[str, Any], score: dict[str, Any]) -> str:
    conflicts = spec_match.get("conflicts") or []
    missing = spec_match.get("missing") or []
    match_score = spec_match.get("score")
    if not supplier:
        return "no_supplier"
    if conflicts:
        return "conflict"
    if missing:
        return "needs_specs"
    if isinstance(match_score, (int, float)) and match_score >= 0.8 and score.get("passed_hard_filter"):
        return "ready"
    return "review"


def _review_summary(spec_match: dict[str, Any], supplier: dict[str, Any]) -> dict[str, Any]:
    conflicts = spec_match.get("conflicts") or []
    missing = spec_match.get("missing") or []
    matched = spec_match.get("matched") or []
    return {
        "matched_count": len(matched),
        "missing_count": len(missing),
        "conflict_count": len(conflicts),
        "needs_manual_check": bool(conflicts or missing or not supplier),
        "top_issues": [*conflicts, *missing][:5],
    }


def _decision_brief(
    score: dict[str, Any],
    profit: dict[str, Any],
    market: dict[str, Any],
    supplier: dict[str, Any],
    spec_match: dict[str, Any],
) -> dict[str, Any]:
    passed = bool(score.get("passed_hard_filter"))
    rejection_reasons = score.get("rejection_reasons") or []
    supplier_source = _supplier_source(supplier) if supplier else "none"
    margin = profit.get("profit_margin")
    match_quality = supplier.get("match_quality_score") if supplier else None
    candidate_score = None
    if supplier:
        raw = supplier.get("raw_data") or {}
        candidate_score = supplier.get("candidate_score", raw.get("supplier_candidate_score"))
    spec_score = spec_match.get("score")
    missing = spec_match.get("missing") or []
    conflicts = spec_match.get("conflicts") or []

    positives: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    next_steps: list[str] = []

    if _has_rich_market_evidence(market):
        positives.append({"code": "market_data_rich", "value": _market_strength_value(market)})
    elif _has_market_evidence(market):
        positives.append({"code": "market_data_basic", "value": None})
    else:
        risks.append({"code": "market_data_missing", "value": None})

    if _has_supplier_evidence(supplier):
        positives.append({"code": "supplier_evidence", "value": supplier_source})
    else:
        risks.append({"code": "supplier_missing", "value": None})

    if isinstance(candidate_score, (int, float)):
        positives.append({"code": "candidate_score", "value": round(candidate_score, 3)})
    if isinstance(match_quality, (int, float)):
        target = positives if match_quality >= 0.55 else risks
        target.append({"code": "match_quality", "value": round(match_quality, 3)})
    if isinstance(spec_score, (int, float)):
        target = positives if spec_score >= 0.7 else risks
        target.append({"code": "spec_match", "value": round(spec_score, 3)})

    if isinstance(margin, (int, float)):
        target = positives if margin >= 0.18 else risks
        target.append({"code": "margin", "value": round(margin, 4)})

    for reason in rejection_reasons[:4]:
        risks.append({"code": f"rejection:{reason}", "value": None})
    for conflict in conflicts[:3]:
        risks.append({"code": f"conflict:{conflict}", "value": None})
    for field in missing[:3]:
        risks.append({"code": f"missing:{field}", "value": None})

    if not supplier:
        action = "blocked_no_supplier"
        confidence = "low"
        next_steps.extend(["find_supplier", "retry_1688"])
    elif passed and not missing and not conflicts and _has_rich_market_evidence(market):
        action = "ready_to_sample"
        confidence = "high"
        next_steps.extend(["open_supplier", "request_quote", "save_shortlist"])
    elif conflicts or missing or rejection_reasons:
        action = "manual_verify"
        confidence = "medium" if _has_supplier_evidence(supplier) and _has_market_evidence(market) else "low"
        if missing or conflicts:
            next_steps.append("verify_specs")
        if "margin_too_low" in rejection_reasons or (isinstance(margin, (int, float)) and margin < 0.18):
            next_steps.append("renegotiate_cost")
        if "supplier_match_too_low" in rejection_reasons or "supplier_spec_too_low" in rejection_reasons:
            next_steps.append("compare_more_suppliers")
        next_steps.append("accept_or_reject_supplier")
    else:
        action = "score_review"
        confidence = "medium"
        next_steps.extend(["inspect_score", "accept_or_reject_supplier"])

    return {
        "action": action,
        "confidence": confidence,
        "positives": _dedupe_signals(positives)[:6],
        "risks": _dedupe_signals(risks)[:8],
        "next_steps": list(dict.fromkeys(next_steps))[:5],
    }


def _market_strength_value(market: dict[str, Any]) -> Any:
    for key in ("est_monthly_sales", "search_volume_monthly", "monthly_purchases", "bsr"):
        value = market.get(key)
        if value not in (None, "", [], {}):
            return {key: value}
    return None


def _dedupe_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for signal in signals:
        code = str(signal.get("code") or "")
        if not code or code in seen:
            continue
        seen.add(code)
        result.append(signal)
    return result


def _amazon_url(product: dict[str, Any]) -> str | None:
    asin = product.get("asin")
    marketplace = str(product.get("marketplace") or "US").upper()
    if not asin:
        return None
    hosts = {
        "US": "www.amazon.com",
        "UK": "www.amazon.co.uk",
        "DE": "www.amazon.de",
        "JP": "www.amazon.co.jp",
    }
    return f"https://{hosts.get(marketplace, 'www.amazon.com')}/dp/{asin}"


def _count_mock(rows: list[dict[str, Any]]) -> int:
    count = 0
    for row in rows:
        suppliers = row.get("suppliers") or []
        if suppliers and _supplier_is_mock(suppliers[0]):
            count += 1
    return count


def _supplier_is_mock(supplier: dict[str, Any]) -> bool:
    if supplier.get("invalid_for_decision"):
        return True
    name = str(supplier.get("supplier_name") or "").lower()
    offer_id = str(supplier.get("alibaba_offer_id") or "")
    return "mock" in name or not offer_id.isdigit()


def _avg_score(rows: list[dict[str, Any]]) -> float | None:
    scores = [(row.get("score") or {}).get("total_score") for row in rows]
    scores = [s for s in scores if isinstance(s, (int, float))]
    return round(sum(scores) / len(scores), 1) if scores else None


def _top_margin(rows: list[dict[str, Any]]) -> float | None:
    margins = [(row.get("profit") or {}).get("profit_margin") for row in rows]
    margins = [m for m in margins if isinstance(m, (int, float))]
    return round(max(margins), 4) if margins else None
