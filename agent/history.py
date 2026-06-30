"""Read exported candidate files and maintain saved selections."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import DATA_DIR, settings

_SAVED_FILE = DATA_DIR / "agent_saved_items.json"


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
        runs.append(run)
        if len(runs) >= limit:
            break
    return runs


def list_results(run_id: str | None = None, limit: int = 200) -> dict[str, Any]:
    saved = _load_saved()
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
            suppliers = row.get("suppliers") or []
            top_supplier = suppliers[0] if suppliers else {}
            key = f"{export_id}:{product.get('asin', '')}"
            item = {
                "key": key,
                "export_id": export_id,
                "asin": product.get("asin"),
                "title": product.get("title"),
                "brand": product.get("brand"),
                "category": product.get("category"),
                "price": product.get("price"),
                "image": product.get("main_image_url"),
                "supplier": top_supplier.get("supplier_name"),
                "offer_url": top_supplier.get("offer_url"),
                "buy_cost_cny": top_supplier.get("base_price_cny"),
                "moq": top_supplier.get("moq"),
                "margin": profit.get("profit_margin"),
                "net_profit": profit.get("net_profit"),
                "score": score.get("total_score"),
                "passed": score.get("passed_hard_filter"),
                "mock": _supplier_is_mock(top_supplier),
                "saved": key in saved,
                "xlsx_file": xlsx.name if xlsx.exists() else None,
            }
            items.append(item)
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


def audit_export(path: Path) -> dict[str, Any]:
    rows = _read_json_list(path)
    mock_count = _count_mock(rows)
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
    return {
        "candidate_count": len(rows),
        "mock_count": mock_count,
        "real_supplier_count": max(0, len(rows) - mock_count),
        "avg_margin": round(sum(margins) / len(margins), 4) if margins else None,
        "suspicious_price_count": len(suspicious_price),
        "suspicious_price_asins": suspicious_price[:20],
    }


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


def _count_mock(rows: list[dict[str, Any]]) -> int:
    count = 0
    for row in rows:
        suppliers = row.get("suppliers") or []
        if suppliers and _supplier_is_mock(suppliers[0]):
            count += 1
    return count


def _supplier_is_mock(supplier: dict[str, Any]) -> bool:
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
