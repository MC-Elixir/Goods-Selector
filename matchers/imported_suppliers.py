"""Imported 1688 supplier candidates from Open Platform API test output."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Iterable

from loguru import logger

from config.settings import DATA_DIR
from matchers.alibaba_pailitao import SupplierDTO
from matchers.alibaba_pifatuan import _find_first_list, _parse_pifatuan_response

_IMPORT_FILE = DATA_DIR / "imported_1688_suppliers.json"

_KEYWORD_ALIASES = (
    ("水杯", ("保温杯", "杯子", "运动水壶", "water bottle", "tumbler", "bottle")),
    ("保温杯", ("水杯", "杯子", "thermos", "insulated bottle", "vacuum bottle")),
    ("瑜伽垫", ("运动垫", "健身垫", "yoga mat", "exercise mat", "fitness mat")),
    ("厨房垫", ("沥水垫", "餐垫", "dish drying mat", "kitchen mat", "sink mat")),
    ("收纳盒", ("收纳箱", "整理盒", "storage box", "organizer")),
    ("枕头", ("靠枕", "睡枕", "pillow")),
    ("手机支架", ("平板支架", "phone stand", "phone holder")),
    ("不锈钢", ("304", "316", "stainless steel")),
    ("硅胶", ("silicone",)),
    ("铝合金", ("铝", "aluminum", "aluminium")),
)


def import_alibaba_supplier_payload(
    payload: Any,
    *,
    keyword: str = "",
    note: str = "",
) -> dict[str, Any]:
    """Parse and persist supplier candidates copied from 1688 API test output."""
    raw = _coerce_payload(payload)
    suppliers = _parse_suppliers(raw)
    if not suppliers:
        raise ValueError("No supplier-like records found in payload")

    data = _read_imports()
    now = time.time()
    imported_keys: list[str] = []
    for supplier in suppliers:
        supplier.raw_data = dict(supplier.raw_data or {})
        supplier.raw_data["source"] = "alibaba_import"
        supplier.raw_data["import_keyword"] = keyword.strip()
        supplier.raw_data["import_note"] = note.strip()
        supplier.raw_data["imported_at"] = now
        key = _supplier_key(supplier)
        data[key] = {
            "key": key,
            "keyword": keyword.strip(),
            "note": note.strip(),
            "imported_at": now,
            "supplier": asdict(supplier),
        }
        imported_keys.append(key)

    _write_imports(data)
    return {
        "imported": len(imported_keys),
        "total": len(data),
        "keys": imported_keys,
        "items": [_entry_summary(data[key]) for key in imported_keys[:10]],
    }


def list_imported_suppliers(limit: int = 200) -> dict[str, Any]:
    entries = sorted(
        _read_imports().values(),
        key=lambda item: float(item.get("imported_at") or 0),
        reverse=True,
    )
    return {
        "items": [_entry_summary(item) for item in entries[:limit]],
        "count": len(entries),
    }


def find_imported_suppliers(
    keywords: Iterable[str],
    top_k: int = 20,
    *,
    allow_recent_fallback: bool = False,
) -> list[SupplierDTO]:
    """Return imported candidates that are relevant to the current product keywords.

    By default, unrelated imports are ignored so a manual/API-test payload for one
    product cannot suppress live 1688 searches for another product.
    """
    keyword_list = [str(k).strip() for k in keywords if str(k).strip()]
    entries = list(_read_imports().values())
    if not entries:
        return []

    ranked: list[tuple[float, float, SupplierDTO]] = []
    for entry in entries:
        supplier = _supplier_from_dict(entry.get("supplier") or {})
        if supplier is None:
            continue
        score = _relevance(entry, supplier, keyword_list)
        if score <= 0 and not allow_recent_fallback:
            continue
        ranked.append((score, float(entry.get("imported_at") or 0), supplier))

    if not ranked:
        return []
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    suppliers = [supplier for _, _, supplier in ranked[:top_k]]
    logger.info(f"[1688-import] loaded {len(suppliers)} relevant imported supplier candidates")
    return suppliers


def _coerce_payload(payload: Any) -> Any:
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            raise ValueError("payload is required")
        return json.loads(text)
    return payload


def _parse_suppliers(raw: Any) -> list[SupplierDTO]:
    if isinstance(raw, dict):
        parsed = _parse_pifatuan_response(raw)
        if parsed:
            return parsed
    items = _find_first_list(raw)
    suppliers = [_item_to_imported_supplier(item) for item in items if isinstance(item, dict)]
    return [supplier for supplier in suppliers if supplier is not None]


def _item_to_imported_supplier(item: dict[str, Any]) -> SupplierDTO | None:
    raw = dict(item)
    offer_id = _first_value(
        item,
        "offerId", "productId", "id", "idStr", "offer_id",
        "supplierId", "companyId", "memberId", "userId",
    )
    title = _first_value(item, "subject", "title", "productTitle", "name", "productName")
    supplier_name = _first_value(item, "supplierName", "companyName", "shopName", "sellerName", "name")
    if not offer_id:
        seed = json.dumps(item, ensure_ascii=False, sort_keys=True)
        offer_id = "import-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    if not (title or supplier_name):
        return None

    offer_id_text = str(offer_id)
    offer_url = _first_value(item, "offerUrl", "productUrl", "url")
    if not offer_url and offer_id_text.isdigit():
        offer_url = f"https://detail.1688.com/offer/{offer_id_text}.html"

    return SupplierDTO(
        alibaba_offer_id=offer_id_text,
        supplier_name=supplier_name,
        offer_url=offer_url,
        offer_image_url=_first_value(item, "mainPictUrl", "imageUrl", "pictureUrl", "mainImage", "image"),
        moq=_to_int(_first_value(item, "minOrderQuantity", "minOrder", "moq")),
        base_price_cny=_to_float(_first_value(item, "price", "priceCny", "minPrice", "unitPrice")),
        monthly_sales=_to_int(_first_value(item, "monthlyOrderNum", "monthlySales", "saleQuantity", "salesVolume")),
        repeat_buyer_rate=_to_float(_first_value(item, "repeatPurchaseRate", "repeatBuyerRate")),
        is_factory=_to_bool(_first_value(item, "isFactory", "factory", "sourceFactory", "factoryFlag")),
        delivery_days=_to_int(_first_value(item, "deliveryDays", "leadTime")),
        title_cn=str(title) if title else None,
        raw_data={**raw, "source": "alibaba_import"},
    )


def _supplier_key(supplier: SupplierDTO) -> str:
    raw = supplier.raw_data or {}
    seed = "|".join([
        supplier.alibaba_offer_id or "",
        supplier.offer_url or "",
        supplier.supplier_name or "",
        supplier.title_cn or "",
        raw.get("import_keyword") or "",
    ])
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    supplier = entry.get("supplier") or {}
    raw = supplier.get("raw_data") or {}
    return {
        "key": entry.get("key"),
        "keyword": entry.get("keyword"),
        "note": entry.get("note"),
        "imported_at": entry.get("imported_at"),
        "offer_id": supplier.get("alibaba_offer_id"),
        "supplier": supplier.get("supplier_name"),
        "title": supplier.get("title_cn") or raw.get("title") or raw.get("subject"),
        "price_cny": supplier.get("base_price_cny"),
        "moq": supplier.get("moq"),
        "monthly_sales": supplier.get("monthly_sales"),
        "source": raw.get("source"),
    }


def _relevance(entry: dict[str, Any], supplier: SupplierDTO, keywords: list[str]) -> float:
    haystack = " ".join([
        str(entry.get("keyword") or ""),
        supplier.title_cn or "",
        supplier.supplier_name or "",
        json.dumps(supplier.raw_data or {}, ensure_ascii=False),
    ]).lower()
    if not keywords:
        return 0.0
    score = 0.0
    for keyword in _expand_keywords(keywords):
        value = keyword.lower()
        if value and value in haystack:
            score += 1.0
    return score


def _expand_keywords(keywords: list[str]) -> list[str]:
    expanded: list[str] = []
    for keyword in keywords:
        value = str(keyword or "").strip()
        if not value:
            continue
        expanded.append(value)
        lowered = value.lower()
        for canonical, aliases in _KEYWORD_ALIASES:
            terms = (canonical, *aliases)
            if any(_term_matches_keyword(term, value, lowered) for term in terms):
                expanded.extend(str(term) for term in terms)
    return _dedupe(expanded)


def _term_matches_keyword(term: str, keyword: str, lowered_keyword: str) -> bool:
    if _is_ascii(term):
        needle = term.lower()
        return needle in lowered_keyword or lowered_keyword in needle
    return term in keyword or keyword in term


def _is_ascii(value: str) -> bool:
    try:
        value.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _supplier_from_dict(data: dict[str, Any]) -> SupplierDTO | None:
    try:
        allowed = {f.name for f in fields(SupplierDTO)}
        return SupplierDTO(**{k: v for k, v in data.items() if k in allowed})
    except Exception as exc:
        logger.debug(f"[1688-import] bad supplier entry ignored: {exc}")
        return None


def _read_imports() -> dict[str, Any]:
    if not _IMPORT_FILE.exists():
        return {}
    try:
        data = json.loads(_IMPORT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_imports(data: dict[str, Any]) -> None:
    _IMPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _IMPORT_FILE.with_suffix(_IMPORT_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_IMPORT_FILE)


def _first_value(parent: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = parent.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "factory", "工厂", "源头工厂"}:
        return True
    if text in {"false", "0", "no", "n", "trader", "贸易商"}:
        return False
    return None
