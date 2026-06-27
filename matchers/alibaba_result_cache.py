from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, fields
from pathlib import Path
from typing import Iterable

from loguru import logger

from config.settings import DATA_DIR
from crawlers.amazon_bsr import ProductDTO
from matchers.alibaba_pailitao import SupplierDTO

_CACHE_DIR = DATA_DIR / "cache" / "1688"
_CACHE_FILE = _CACHE_DIR / "real_supplier_results.json"
_CIRCUIT_FILE = _CACHE_DIR / "circuit_breaker.json"


def make_cache_key(product: ProductDTO, keywords: Iterable[str], top_k: int) -> str:
    """Stable key for reusing real 1688 matches across reruns."""
    payload = {
        "asin": product.asin,
        "title": product.title,
        "image": product.main_image_url,
        "keywords": list(keywords)[:5],
        "top_k": top_k,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_cached_suppliers(key: str, ttl_seconds: int) -> list[SupplierDTO]:
    if ttl_seconds <= 0:
        return []

    data = _read_json(_CACHE_FILE, default={})
    entry = data.get(key)
    if not entry:
        return []

    created_at = float(entry.get("created_at") or 0)
    if time.time() - created_at > ttl_seconds:
        return []

    suppliers = [_supplier_from_dict(item) for item in entry.get("suppliers", [])]
    suppliers = [s for s in suppliers if s is not None and is_real_supplier(s)]
    if suppliers:
        logger.info(f"[1688-cache] hit key={key[:10]} suppliers={len(suppliers)}")
    return suppliers


def save_cached_suppliers(key: str, suppliers: list[SupplierDTO]) -> None:
    real_suppliers = [s for s in suppliers if is_real_supplier(s)]
    if not real_suppliers:
        return

    data = _read_json(_CACHE_FILE, default={})
    data[key] = {
        "created_at": time.time(),
        "suppliers": [asdict(s) for s in real_suppliers],
    }
    _write_json(_CACHE_FILE, data)
    logger.info(f"[1688-cache] saved key={key[:10]} suppliers={len(real_suppliers)}")


def is_real_supplier(supplier: SupplierDTO) -> bool:
    method = (supplier.match_verification_method or "").lower()
    if method == "mock":
        return False
    offer_id = supplier.alibaba_offer_id or ""
    return offer_id.isdigit() and len(offer_id) >= 8


def circuit_is_open() -> bool:
    state = _read_json(_CIRCUIT_FILE, default={})
    blocked_until = float(state.get("blocked_until") or 0)
    if blocked_until <= time.time():
        return False
    logger.warning(
        f"[1688-circuit] open until {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(blocked_until))}"
    )
    return True


def open_circuit(cooldown_seconds: int, reason: str) -> None:
    if cooldown_seconds <= 0:
        return
    _write_json(
        _CIRCUIT_FILE,
        {
            "blocked_until": time.time() + cooldown_seconds,
            "reason": reason,
            "updated_at": time.time(),
        },
    )
    logger.warning(f"[1688-circuit] opened for {cooldown_seconds}s: {reason}")


def reset_circuit() -> None:
    if _CIRCUIT_FILE.exists():
        try:
            _CIRCUIT_FILE.unlink()
        except OSError as exc:
            logger.debug(f"[1688-circuit] reset failed: {exc}")


def _supplier_from_dict(data: dict) -> SupplierDTO | None:
    try:
        allowed = {f.name for f in fields(SupplierDTO)}
        return SupplierDTO(**{k: v for k, v in data.items() if k in allowed})
    except Exception as exc:
        logger.debug(f"[1688-cache] bad supplier entry ignored: {exc}")
        return None


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug(f"[1688-cache] read failed {path}: {exc}")
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
