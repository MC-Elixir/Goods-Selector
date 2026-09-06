"""
1688 分销严选开放平台搜索
=========================

使用 alibaba.pifatuan.product.list 获取供应商候选。这个路径依赖
ALIBABA_APP_KEY / ALIBABA_APP_SECRET / ALIBABA_ACCESS_TOKEN，比浏览器搜索更适合在
1688 TMD 验证码频繁出现时作为优先后端。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote

import requests
from loguru import logger
from requests import Response
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from matchers.alibaba_detail import apply_1688_detail_to_supplier
from matchers.alibaba_pailitao import SupplierDTO, md5_sign

_NAMESPACE = "com.alibaba.pifatuan"
_PRODUCT_LIST_METHOD = "alibaba.pifatuan.product.list"
_PAGE_SIZE = 20


@dataclass(frozen=True)
class SupplierSearchApi:
    namespace: str
    method: str
    keyword_param: str = "keywords"

    @property
    def label(self) -> str:
        return f"{self.namespace}/{self.method}:{self.keyword_param}"


class AlibabaPifatuanSearch:
    """Search 1688 distribution products through the Open Platform."""

    def __init__(
        self,
        app_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        gateway: Optional[str] = None,
        namespace: Optional[str] = None,
        method: Optional[str] = None,
        keyword_param: Optional[str] = None,
    ):
        self.app_key = settings.alibaba_app_key if app_key is None else app_key
        self.app_secret = settings.alibaba_app_secret if app_secret is None else app_secret
        self.access_token = settings.alibaba_access_token if access_token is None else access_token
        self.gateway = (settings.alibaba_api_gateway if gateway is None else gateway).rstrip("/")
        self.namespace = (settings.alibaba_supplier_search_namespace if namespace is None else namespace).strip() or _NAMESPACE
        self.method = (settings.alibaba_supplier_search_method if method is None else method).strip() or _PRODUCT_LIST_METHOD
        self.keyword_param = (
            settings.alibaba_supplier_search_keyword_param if keyword_param is None else keyword_param
        ).strip() or "keywords"
        self._cache = _make_cache("pifatuan_search")
        self.last_attempts: list[dict[str, Any]] = []

    def configured(self) -> bool:
        return bool(self.app_key and self.app_secret and self.access_token)

    def search(self, keywords: list[str], top_k: int = 20) -> list[SupplierDTO]:
        if not self.configured():
            raise RuntimeError("1688 pifatuan API not configured")

        attempts: list[dict[str, Any]] = []
        last_error: Exception | None = None
        for api in self.search_apis():
            try:
                suppliers = self._search_with_api(keywords, top_k, api)
                attempts.append({
                    "namespace": api.namespace,
                    "method": api.method,
                    "keyword_param": api.keyword_param,
                    "ok": True,
                    "count": len(suppliers),
                    "error": None,
                })
                self.last_attempts = attempts
                if suppliers:
                    self.namespace = api.namespace
                    self.method = api.method
                    self.keyword_param = api.keyword_param
                    return suppliers
            except Exception as exc:
                last_error = exc
                attempts.append({
                    "namespace": api.namespace,
                    "method": api.method,
                    "keyword_param": api.keyword_param,
                    "ok": False,
                    "count": 0,
                    "error": str(exc),
                })
                continue

        self.last_attempts = attempts
        if last_error:
            raise RuntimeError(_summarize_attempt_errors(attempts))
        return []

    def _search_with_api(
        self,
        keywords: list[str],
        top_k: int,
        api: SupplierSearchApi,
    ) -> list[SupplierDTO]:
        seen: set[str] = set()
        results: list[SupplierDTO] = []
        for keyword in keywords:
            if len(results) >= top_k:
                break
            for supplier in self._search_one_keyword(keyword, api):
                if not supplier.alibaba_offer_id or supplier.alibaba_offer_id in seen:
                    continue
                seen.add(supplier.alibaba_offer_id)
                results.append(supplier)

        results.sort(
            key=lambda s: (
                s.monthly_sales or 0,
                1 if s.is_factory else 0,
                -(s.moq or 999999),
            ),
            reverse=True,
        )
        logger.info(f"[1688-pft] 搜索完成，共 {len(results)} 条结果（关键词数={len(keywords)}）")
        return results[:top_k]

    def search_apis(self) -> list[SupplierSearchApi]:
        primary = SupplierSearchApi(self.namespace, self.method, self.keyword_param)
        apis = [primary, *_parse_candidate_apis(settings.alibaba_supplier_search_candidates)]
        unique: list[SupplierSearchApi] = []
        seen: set[tuple[str, str, str]] = set()
        for api in apis:
            key = (api.namespace, api.method, api.keyword_param)
            if key in seen:
                continue
            seen.add(key)
            unique.append(api)
        return unique

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=True,
    )
    def _search_one_keyword(self, keyword: str, api: SupplierSearchApi) -> list[SupplierDTO]:
        cache_key = f"pft_{api.namespace}_{api.method}_{api.keyword_param}_{keyword}_{_PAGE_SIZE}"
        if self._cache is not None and cache_key in self._cache:
            return self._cache[cache_key]

        params = {
            "pageSize": _PAGE_SIZE,
            "pageNum": 1,
            api.keyword_param: keyword,
        }
        payload = self._build_payload(params)
        url = f"{self.gateway}/param2/1/{api.namespace}/{api.method}/{self.app_key}"
        resp = requests.post(
            url,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
        raw = _response_payload(resp)
        if getattr(resp, "status_code", 200) >= 400:
            raise RuntimeError(_http_error_message(resp, raw, keyword))
        _check_error(raw, keyword)
        suppliers = _parse_pifatuan_response(raw)
        if self._cache is not None:
            self._cache.set(cache_key, suppliers, expire=settings.cache_ttl_seconds)
        return suppliers

    def _build_payload(self, params: dict[str, Any]) -> str:
        signed = {**params, "_aop_signature": md5_sign(params, self.app_secret)}
        return (
            f"param2={quote(json.dumps(signed, ensure_ascii=False, separators=(',', ':')))}"
            f"&access_token={quote(self.access_token or '')}"
        )


def _parse_candidate_apis(raw: str) -> list[SupplierSearchApi]:
    apis: list[SupplierSearchApi] = []
    for line in (raw or "").replace(";", "\n").splitlines():
        spec = line.strip()
        if not spec or spec.startswith("#"):
            continue
        if "|" in spec:
            parts = [p.strip() for p in spec.split("|")]
        else:
            keyword_param = "keywords"
            left = spec
            if ":" in spec:
                left, keyword_param = [p.strip() for p in spec.rsplit(":", 1)]
            if "/" in left:
                namespace, method = [p.strip() for p in left.split("/", 1)]
                parts = [namespace, method, keyword_param]
            else:
                parts = []
        if len(parts) < 2:
            continue
        namespace = parts[0]
        method = parts[1]
        keyword_param = parts[2] if len(parts) > 2 and parts[2] else "keywords"
        if namespace and method:
            apis.append(SupplierSearchApi(namespace, method, keyword_param))
    return apis


def _summarize_attempt_errors(attempts: list[dict[str, Any]]) -> str:
    parts = []
    for item in attempts[:5]:
        label = f"{item.get('namespace')}/{item.get('method')}:{item.get('keyword_param')}"
        if item.get("error"):
            parts.append(f"{label} -> {item['error']}")
    return "；".join(parts) or "1688 OpenAPI supplier search failed"


def _response_payload(resp: Response) -> dict[str, Any]:
    try:
        raw = resp.json()
    except ValueError:
        text = (resp.text or "").strip()
        return {"raw_text": text[:1000]} if text else {}
    return raw if isinstance(raw, dict) else {"raw_response": raw}


def _http_error_message(resp: Response, raw: dict[str, Any], keyword: str) -> str:
    status_code = getattr(resp, "status_code", 0)
    code = (
        raw.get("error_code")
        or raw.get("errorCode")
        or raw.get("code")
        or status_code
    )
    msg = (
        raw.get("error_message")
        or raw.get("errorMessage")
        or raw.get("message")
        or raw.get("sub_msg")
        or raw.get("raw_text")
        or getattr(resp, "reason", "")
        or ""
    )
    return f"1688 pifatuan HTTP {status_code} [{code}] keyword={keyword!r}: {msg}"


def _check_error(raw: dict[str, Any], keyword: str) -> None:
    success = raw.get("success")
    if success is False or raw.get("error_code") or raw.get("errorCode"):
        code = raw.get("error_code") or raw.get("errorCode") or "unknown"
        msg = raw.get("error_message") or raw.get("errorMessage") or raw.get("message") or ""
        raise RuntimeError(f"1688 pifatuan API 错误 [{code}] keyword={keyword!r}: {msg}")


def _parse_pifatuan_response(raw: dict[str, Any]) -> list[SupplierDTO]:
    items = _find_first_list(raw)
    suppliers: list[SupplierDTO] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dto = _item_to_supplier(item)
        if dto.alibaba_offer_id:
            suppliers.append(dto)
    return suppliers


def _find_first_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []

    preferred_keys = (
        "offerList", "productList", "products", "items", "list", "dataList", "records",
    )
    for key in preferred_keys:
        child = value.get(key)
        if isinstance(child, list):
            return child

    for key in ("result", "data", "content"):
        child = value.get(key)
        found = _find_first_list(child)
        if found:
            return found

    for child in value.values():
        found = _find_first_list(child)
        if found:
            return found
    return []


def _item_to_supplier(item: dict[str, Any]) -> SupplierDTO:
    sale = _first_dict(item, "saleInfo", "sale", "priceInfo")
    supplier = _first_dict(item, "supplierInfo", "supplier", "shopInfo", "sellerInfo")
    product = _first_dict(item, "productInfo", "product", "imageInfo")
    trade = _first_dict(item, "tradeInfo", "trade", "statistics")

    offer_id = str(_first_value(item, "offerId", "productId", "id", "idStr", "offer_id") or "")
    title = _first_value(item, "subject", "title", "productTitle", "name") or _first_value(product, "subject", "title", "name")
    price_tiers = _price_tiers(sale)
    base_price = _first_price(price_tiers) or _to_float(_first_value(item, "price", "priceCny", "minPrice") or _first_value(sale, "price", "minPrice"))

    image_url = (
        _first_value(product, "mainPictUrl", "imageUrl", "pictureUrl", "mainImage")
        or _first_value(item, "mainPictUrl", "imageUrl", "pictureUrl", "image")
    )
    monthly_sales = _to_int(
        _first_value(trade, "monthlyOrderNum", "monthlySales", "saleQuantity", "salesVolume")
        or _first_value(item, "monthlyOrderNum", "monthlySales", "salesVolume")
    )
    repeat_rate = _to_float(
        _first_value(trade, "repeatPurchaseRate", "repeatBuyerRate")
        or _first_value(item, "repeatPurchaseRate", "repeatBuyerRate")
    )
    factory_value = _first_value(supplier, "isFactory", "factory", "sourceFactory", "factoryFlag")
    supplier_type = str(_first_value(supplier, "supplierType", "businessType", "companyType") or "")

    dto = SupplierDTO(
        alibaba_offer_id=offer_id,
        supplier_name=_first_value(supplier, "supplierName", "companyName", "shopName", "name"),
        offer_url=_first_value(item, "offerUrl", "productUrl", "url") or f"https://detail.1688.com/offer/{offer_id}.html",
        offer_image_url=image_url,
        image_similarity=None,
        text_similarity=None,
        moq=_to_int(_first_value(sale, "minOrderQuantity", "minOrder", "moq") or _first_value(item, "minOrderQuantity", "moq")),
        base_price_cny=base_price,
        price_tiers=price_tiers,
        monthly_sales=monthly_sales,
        repeat_buyer_rate=repeat_rate,
        is_factory=_to_bool(factory_value) or ("工厂" in supplier_type or "factory" in supplier_type.lower()),
        delivery_days=_to_int(_first_value(item, "deliveryDays", "leadTime") or _first_value(sale, "deliveryDays", "leadTime")),
        fba_ready=None,
        title_cn=str(title) if title else None,
        raw_data={**item, "source": "alibaba_pifatuan"},
    )
    return apply_1688_detail_to_supplier(dto, item)


def _first_dict(parent: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = parent.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _first_value(parent: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = parent.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _price_tiers(sale: dict[str, Any]) -> list[dict[str, Any]]:
    raw_tiers = sale.get("priceRangeList") or sale.get("priceRanges") or []
    tiers: list[dict[str, Any]] = []
    for tier in raw_tiers if isinstance(raw_tiers, list) else []:
        if not isinstance(tier, dict):
            continue
        qty = _to_int(_first_value(tier, "startQuantity", "beginAmount", "quantity")) or 1
        price = _to_float(_first_value(tier, "price", "unitPrice"))
        if price is not None:
            tiers.append({"qty": qty, "price": price})
    return tiers


def _first_price(tiers: list[dict[str, Any]]) -> Optional[float]:
    if not tiers:
        return None
    return _to_float(tiers[min(1, len(tiers) - 1)].get("price"))


def _to_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}


def _make_cache(ns: str):
    if not settings.enable_api_cache:
        return None
    try:
        import diskcache as dc
        return dc.Cache(str(settings.cache_dir / ns))
    except ImportError:
        return None
