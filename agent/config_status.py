"""Sanitized runtime configuration status for UI and diagnostics."""
from __future__ import annotations

import os
from typing import Any

from agent.alibaba_diagnostics import (
    load_alibaba_open_diagnostic,
    save_alibaba_open_diagnostic,
)
from agent.browser_agent import allowed_domains as browser_agent_allowed_domains
from agent.browser_agent import browser_agent_available
from agent.env_file import set_env_values
from agent.seller_sprite_diagnostics import (
    load_seller_sprite_diagnostic,
    save_seller_sprite_diagnostic,
)
from config.settings import PROJECT_ROOT, settings


def get_config_status() -> dict[str, Any]:
    """Return capability readiness without exposing secrets."""
    seller_sprite_configured = bool(settings.mjjl_api_key)
    vision_configured = bool(settings.ppio_api_key or settings.anthropic_api_key)
    alibaba_open_configured = bool(
        settings.alibaba_app_key
        and settings.alibaba_app_secret
        and settings.alibaba_access_token
    )
    return {
        "seller_sprite": {
            "configured": seller_sprite_configured,
            "base_url": settings.mjjl_api_base if seller_sprite_configured else "",
            "env": "MJJL_API_KEY",
            "key_length": len(settings.mjjl_api_key or ""),
            "max_products_per_run": max(int(settings.mjjl_max_products_per_run or 0), 0),
            "last_check": load_seller_sprite_diagnostic(),
        },
        "vision": {
            "configured": vision_configured,
            "provider": settings.vision_provider if vision_configured else "none",
            "llm_verification_enabled": bool(settings.enable_llm_verification),
        },
        "alibaba_open": {
            "configured": alibaba_open_configured,
            "gateway": settings.alibaba_api_gateway if alibaba_open_configured else "",
            "namespace": settings.alibaba_supplier_search_namespace if alibaba_open_configured else "",
            "method": settings.alibaba_supplier_search_method if alibaba_open_configured else "",
            "keyword_param": settings.alibaba_supplier_search_keyword_param if alibaba_open_configured else "",
            "candidates": settings.alibaba_supplier_search_candidates if alibaba_open_configured else "",
            "has_app_key": bool(settings.alibaba_app_key),
            "has_app_secret": bool(settings.alibaba_app_secret),
            "has_access_token": bool(settings.alibaba_access_token),
            "last_check": load_alibaba_open_diagnostic(),
        },
        "runtime": {
            "allow_mock_suppliers": bool(settings.alibaba_allow_mock_suppliers),
            "enable_scrapling_matcher": bool(settings.enable_scrapling_matcher),
            "cache_enabled": bool(settings.enable_api_cache),
        },
        "browser_agent": {
            "configured": browser_agent_available(),
            "tool": "browser-use",
            "mode": "local",
            "allowed_domains": browser_agent_allowed_domains(),
            "cdp_http_configured": bool((os.getenv("BU_CDP_HTTP") or "").strip()),
            "cdp_ws_configured": bool((os.getenv("BU_CDP_WS") or "").strip()),
        },
    }


def configure_seller_sprite(api_key: str, base_url: str | None = None) -> dict[str, Any]:
    """Persist SellerSprite config without returning the secret."""
    key = (api_key or "").strip()
    if not key:
        raise ValueError("SellerSprite API key is required")
    updates = {"MJJL_API_KEY": key}
    base = (base_url or "").strip()
    if base:
        updates["MJJL_API_BASE"] = base

    changed = set_env_values(PROJECT_ROOT / ".env", updates)
    settings.mjjl_api_key = key
    if base:
        settings.mjjl_api_base = base
    return {
        "configured": True,
        "updated": changed,
        "key_length": len(key),
        "status": get_config_status()["seller_sprite"],
    }


def configure_alibaba_supplier_search(
    namespace: str,
    method: str,
    keyword_param: str | None = None,
    candidates: str | None = None,
) -> dict[str, Any]:
    """Persist the configured 1688 supplier-search OpenAPI method."""
    ns = (namespace or "").strip()
    api = (method or "").strip()
    key_param = (keyword_param or "keywords").strip()
    if not ns:
        raise ValueError("namespace is required")
    if not api:
        raise ValueError("method is required")
    if not key_param:
        raise ValueError("keyword_param is required")

    updates = {
        "ALIBABA_SUPPLIER_SEARCH_NAMESPACE": ns,
        "ALIBABA_SUPPLIER_SEARCH_METHOD": api,
        "ALIBABA_SUPPLIER_SEARCH_KEYWORD_PARAM": key_param,
    }
    if candidates is not None:
        updates["ALIBABA_SUPPLIER_SEARCH_CANDIDATES"] = candidates.strip()
    changed = set_env_values(PROJECT_ROOT / ".env", updates)
    settings.alibaba_supplier_search_namespace = ns
    settings.alibaba_supplier_search_method = api
    settings.alibaba_supplier_search_keyword_param = key_param
    if candidates is not None:
        settings.alibaba_supplier_search_candidates = candidates.strip()
    return {
        "configured": True,
        "updated": changed,
        "namespace": ns,
        "method": api,
        "keyword_param": key_param,
        "candidates": settings.alibaba_supplier_search_candidates,
        "status": get_config_status()["alibaba_open"],
    }


def check_seller_sprite_asin(asin: str, marketplace: str = "US") -> dict[str, Any]:
    """Call a single SellerSprite ASIN detail endpoint and return sanitized evidence."""
    value = (asin or "").strip().upper()
    if not value:
        raise ValueError("ASIN is required")
    site = (marketplace or "US").strip().upper()
    if site not in {"US", "UK", "DE", "JP"}:
        raise ValueError("marketplace must be one of US, UK, DE, JP")

    from analyzers.maijiajingling import MaijiajinglingClient

    with MaijiajinglingClient() as client:
        payload: dict[str, Any] = {
            "configured": bool(client.api_key),
            "base_url": client.base_url,
            "key_length": len(client.api_key or ""),
            "asin": value,
            "marketplace": site,
            "has_market_evidence": False,
            "evidence_source": None,
            "api_checks": [],
            "error": None,
        }
        try:
            detail = client.asin_detail(site, value)
            payload.update({
                "asin": detail.asin or value,
                "title": detail.title,
                "brand": detail.brand,
                "price": detail.price or detail.list_price,
                "rating": detail.rating,
                "review_count": detail.review_count,
                "bsr": detail.bsr,
                "bsr_category": detail.bsr_category_name,
                "category_path": detail.category_path,
                "has_market_evidence": bool(detail),
                "evidence_source": "asin_detail" if detail else None,
            })
        except Exception as exc:
            payload["api_checks"].append({
                "name": "asin_detail",
                "ok": False,
                "evidence": False,
                "error": str(exc),
            })
        else:
            payload["api_checks"].append({
                "name": "asin_detail",
                "ok": True,
                "evidence": bool(payload.get("has_market_evidence")),
                "error": None,
            })

        if not payload["has_market_evidence"]:
            try:
                comp_data = client.competitor_lookup(site, asins=[value], size=10)
                items = _seller_sprite_items(comp_data)
                payload["api_checks"].append({
                    "name": "competitor_lookup",
                    "ok": True,
                    "evidence": bool(items),
                    "error": None,
                })
                if items:
                    target = next(
                        (i for i in items if str(i.get("asin") or "").upper() == value),
                        items[0],
                    )
                    payload.update({
                        "title": payload.get("title") or target.get("title") or target.get("productTitle"),
                        "brand": payload.get("brand") or target.get("brand"),
                        "price": payload.get("price") or _seller_sprite_number(target, "price", "listPrice", "buyBoxPrice"),
                        "rating": payload.get("rating") or _seller_sprite_number(target, "rating", "ratingValue"),
                        "review_count": payload.get("review_count") or _seller_sprite_int(target, "reviewCount", "review_count", "reviews", "ratings"),
                        "bsr": payload.get("bsr") or _seller_sprite_int(target, "bsr", "bsrRank"),
                        "est_monthly_sales": _seller_sprite_int(
                            target,
                            "units",
                            "amzUnit",
                            "totalUnits",
                            "total_units",
                            "monthlySales",
                            "monthly_sales",
                        ),
                        "competing_listings": len(items),
                        "has_market_evidence": True,
                        "evidence_source": "competitor_lookup",
                    })
            except Exception as exc:
                payload["api_checks"].append({
                    "name": "competitor_lookup",
                    "ok": False,
                    "evidence": False,
                    "error": str(exc),
                })

        if not payload["has_market_evidence"]:
            errors = [
                f"{item['name']}: {item['error']}"
                for item in payload["api_checks"]
                if item.get("error")
            ]
            payload["error"] = "；".join(errors) or "No SellerSprite market evidence returned"
    payload["last_check"] = save_seller_sprite_diagnostic(payload)
    return payload


def check_seller_sprite_capabilities(
    asin: str = "B01M16WBW1",
    marketplace: str = "US",
    keyword: str = "water bottle",
) -> dict[str, Any]:
    """Probe a small set of SellerSprite APIs without exposing the key.

    The visits endpoint is not a reliable readiness signal because some keys
    lack that specific permission even when data APIs are enabled. This probe
    checks the concrete data APIs used by the sourcing pipeline with tiny
    requests and records which capabilities are actually usable.
    """
    value = (asin or "").strip().upper()
    if not value:
        raise ValueError("ASIN is required")
    site = (marketplace or "US").strip().upper()
    if site not in {"US", "UK", "DE", "JP"}:
        raise ValueError("marketplace must be one of US, UK, DE, JP")
    term = (keyword or "").strip()[:120] or "water bottle"

    from analyzers.maijiajingling import MaijiajinglingClient

    with MaijiajinglingClient() as client:
        payload: dict[str, Any] = {
            "configured": bool(client.api_key),
            "base_url": client.base_url,
            "key_length": len(client.api_key or ""),
            "asin": value,
            "marketplace": site,
            "keyword": term,
            "has_market_evidence": False,
            "evidence_source": None,
            "authorized_api_count": 0,
            "authorized_data_api_count": 0,
            "api_checks": [],
            "error": None,
        }
        checks = [
            (
                "visits",
                lambda: client.get_visits(),
                lambda body: _seller_sprite_ok(body),
                False,
            ),
            (
                "asin_detail",
                lambda: client.asin_detail(site, value),
                bool,
                True,
            ),
            (
                "competitor_lookup",
                lambda: client.competitor_lookup(site, asins=[value], size=1),
                lambda body: bool(_seller_sprite_items(body)),
                True,
            ),
            (
                "bsr_prediction",
                lambda: client.bsr_prediction(site, bsr=2, category_id="11260432011"),
                bool,
                False,
            ),
            (
                "keyword_research_trends",
                lambda: client.keyword_research_trends(term, marketplace=site),
                lambda body: bool(_seller_sprite_items(body)),
                False,
            ),
        ]

        for name, call, has_evidence, product_level in checks:
            try:
                result = call()
                evidence = bool(has_evidence(result))
                error = _seller_sprite_non_ok_message(result) if not evidence else None
                payload["api_checks"].append({
                    "name": name,
                    "ok": evidence,
                    "evidence": evidence,
                    "error": error,
                })
                if evidence:
                    payload["authorized_api_count"] += 1
                    if name != "visits":
                        payload["authorized_data_api_count"] += 1
                    if product_level and not payload["has_market_evidence"]:
                        payload["has_market_evidence"] = True
                        payload["evidence_source"] = name
                        _merge_seller_sprite_probe_result(payload, name, result)
            except Exception as exc:
                payload["api_checks"].append({
                    "name": name,
                    "ok": False,
                    "evidence": False,
                    "error": str(exc),
                })

        if not payload["authorized_data_api_count"]:
            errors = [
                f"{item['name']}: {item['error']}"
                for item in payload["api_checks"]
                if item.get("error")
            ]
            payload["error"] = "；".join(errors) or "No SellerSprite data API evidence returned"
        elif not payload["has_market_evidence"]:
            payload["error"] = (
                "SellerSprite key has some API permission but no ASIN/competitor "
                "market evidence for sourcing"
            )
    payload["last_check"] = save_seller_sprite_diagnostic(payload)
    return payload


def _seller_sprite_ok(body: Any) -> bool:
    return isinstance(body, dict) and body.get("code") == "OK"


def _seller_sprite_non_ok_message(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    code = body.get("code")
    if code in (None, "OK"):
        return None
    message = body.get("message")
    return str(message or code)


def _merge_seller_sprite_probe_result(payload: dict[str, Any], name: str, result: Any) -> None:
    if name == "asin_detail":
        payload.update({
            "title": getattr(result, "title", None),
            "brand": getattr(result, "brand", None),
            "price": getattr(result, "price", None) or getattr(result, "list_price", None),
            "rating": getattr(result, "rating", None),
            "review_count": getattr(result, "review_count", None),
            "bsr": getattr(result, "bsr", None),
            "bsr_category": getattr(result, "bsr_category_name", None),
        })
        return
    if name == "competitor_lookup" and isinstance(result, dict):
        items = _seller_sprite_items(result)
        target = next(
            (i for i in items if str(i.get("asin") or "").upper() == payload["asin"]),
            items[0] if items else {},
        )
        payload.update({
            "title": target.get("title") or target.get("productTitle"),
            "brand": target.get("brand"),
            "price": _seller_sprite_number(target, "price", "listPrice", "buyBoxPrice"),
            "rating": _seller_sprite_number(target, "rating", "ratingValue"),
            "review_count": _seller_sprite_int(target, "reviewCount", "review_count", "reviews", "ratings"),
            "bsr": _seller_sprite_int(target, "bsr", "bsrRank"),
            "est_monthly_sales": _seller_sprite_int(
                target,
                "units",
                "amzUnit",
                "totalUnits",
                "total_units",
                "monthlySales",
                "monthly_sales",
            ),
            "competing_listings": len(items),
        })


def _seller_sprite_items(body: dict[str, Any]) -> list[dict[str, Any]]:
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("items", "list", "records", "rows"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [data] if data else []
    return []


def _seller_sprite_number(item: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get("amount")
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            continue
    return None


def _seller_sprite_int(item: dict[str, Any], *keys: str) -> int | None:
    value = _seller_sprite_number(item, *keys)
    return int(value) if value is not None else None


def check_alibaba_pifatuan(keyword: str = "水杯", limit: int = 3) -> dict[str, Any]:
    """Call one small 1688 pifatuan search and return sanitized supplier evidence."""
    value = (keyword or "").strip()
    if not value:
        raise ValueError("keyword is required")
    max_results = max(1, min(int(limit or 3), 10))

    from matchers.alibaba_pifatuan import AlibabaPifatuanSearch

    client = AlibabaPifatuanSearch()
    payload: dict[str, Any] = {
        "configured": client.configured(),
        "gateway": client.gateway if client.configured() else "",
        "namespace": getattr(client, "namespace", settings.alibaba_supplier_search_namespace),
        "method": getattr(client, "method", settings.alibaba_supplier_search_method),
        "keyword_param": getattr(client, "keyword_param", settings.alibaba_supplier_search_keyword_param),
        "candidates": settings.alibaba_supplier_search_candidates,
        "keyword": value,
        "limit": max_results,
        "count": 0,
        "suppliers": [],
        "attempts": [],
        "error": None,
    }
    if not client.configured():
        payload["error"] = "ALIBABA_APP_KEY / ALIBABA_APP_SECRET / ALIBABA_ACCESS_TOKEN required"
        payload["last_check"] = save_alibaba_open_diagnostic(payload)
        return payload

    try:
        suppliers = client.search([value], top_k=max_results)
        payload["attempts"] = getattr(client, "last_attempts", [])
        payload["namespace"] = getattr(client, "namespace", payload["namespace"])
        payload["method"] = getattr(client, "method", payload["method"])
        payload["keyword_param"] = getattr(client, "keyword_param", payload["keyword_param"])
        payload["count"] = len(suppliers)
        payload["suppliers"] = [
            {
                "offer_id": supplier.alibaba_offer_id,
                "supplier": supplier.supplier_name,
                "title": supplier.title_cn,
                "price_cny": supplier.base_price_cny,
                "moq": supplier.moq,
                "monthly_sales": supplier.monthly_sales,
                "repeat_buyer_rate": supplier.repeat_buyer_rate,
                "is_factory": supplier.is_factory,
                "source": (supplier.raw_data or {}).get("source"),
            }
            for supplier in suppliers[:max_results]
        ]
    except Exception as exc:
        payload["attempts"] = getattr(client, "last_attempts", [])
        payload["error"] = str(exc)
    payload["last_check"] = save_alibaba_open_diagnostic(payload)
    return payload
