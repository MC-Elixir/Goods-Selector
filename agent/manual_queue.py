"""Manual review queue for sourcing items blocked by external sites."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable

from config.settings import DATA_DIR
from crawlers.amazon_bsr import ProductDTO

_QUEUE_FILE = DATA_DIR / "manual_sourcing_queue.json"


def enqueue_sourcing_block(
    product: ProductDTO,
    keywords: Iterable[str],
    reason: str,
    source: str = "1688",
) -> dict[str, Any]:
    """Create or update a manual sourcing queue item for a blocked product."""
    data = _read_queue()
    key = _item_key(product)
    now = time.time()
    item = data.get(key) or {
        "key": key,
        "asin": product.asin,
        "marketplace": product.marketplace,
        "title": product.title,
        "brand": product.brand,
        "category": product.category,
        "price": product.price,
        "main_image_url": product.main_image_url,
        "listing_url": product.listing_url,
        "created_at": now,
        "status": "open",
        "attempts": 0,
        "notes": [],
    }
    item.update({
        "source": source,
        "keywords": list(keywords)[:8],
        "reason": reason,
        "updated_at": now,
        "attempts": int(item.get("attempts") or 0) + 1,
    })
    data[key] = item
    _write_queue(data)
    return item


def list_manual_queue(status: str | None = None, limit: int = 200) -> dict[str, Any]:
    data = _read_queue()
    items = sorted(data.values(), key=lambda item: float(item.get("updated_at") or 0), reverse=True)
    if status:
        items = [item for item in items if item.get("status") == status]
    return {"items": items[:limit], "count": len(items)}


def update_manual_item(key: str, status: str | None = None, note: str | None = None) -> dict[str, Any]:
    if status and status not in {"open", "resolved", "ignored"}:
        raise ValueError("status must be open, resolved, or ignored")
    data = _read_queue()
    item = data.get(key)
    if not item:
        raise KeyError(key)
    now = time.time()
    if status:
        item["status"] = status
    if note:
        notes = item.setdefault("notes", [])
        notes.append({"text": note, "created_at": now})
    item["updated_at"] = now
    data[key] = item
    _write_queue(data)
    return item


def manual_queue_summary() -> dict[str, int]:
    items = list(_read_queue().values())
    return {
        "open": sum(1 for item in items if item.get("status") == "open"),
        "resolved": sum(1 for item in items if item.get("status") == "resolved"),
        "ignored": sum(1 for item in items if item.get("status") == "ignored"),
        "total": len(items),
    }


def _item_key(product: ProductDTO) -> str:
    return f"{product.marketplace}:{product.asin}"


def _read_queue() -> dict[str, Any]:
    if not _QUEUE_FILE.exists():
        return {}
    try:
        data = json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(data, list):
        return {str(item.get("key")): item for item in data if isinstance(item, dict) and item.get("key")}
    return data if isinstance(data, dict) else {}


def _write_queue(data: dict[str, Any]) -> None:
    _QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _QUEUE_FILE.with_suffix(_QUEUE_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_QUEUE_FILE)
