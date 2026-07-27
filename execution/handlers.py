"""Serializable adapters for existing pipeline DTOs."""
from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any, TypeVar

from analyzers.maijiajingling import MarketAnalysisDTO
from analyzers.profit_model import ProfitBreakdown
from analyzers.scorer import ScoreBreakdown
from crawlers.amazon_bsr import ProductDTO
from execution.repository import json_snapshot
from matchers.alibaba_pailitao import SupplierDTO


T = TypeVar("T")


def dump_dto(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not is_dataclass(value):
        raise TypeError(f"expected dataclass DTO, got {type(value).__name__}")
    payload = asdict(value)
    payload["schema_version"] = "1.0"
    return json_snapshot(payload)


def _load_dataclass(cls: type[T], payload: dict[str, Any] | None) -> T | None:
    if payload is None:
        return None
    allowed = {item.name for item in fields(cls)}
    values = {key: value for key, value in payload.items() if key in allowed}
    if cls is MarketAnalysisDTO and isinstance(values.get("available_date"), str):
        values["available_date"] = datetime.fromisoformat(values["available_date"])
    return cls(**values)


def dump_product(product: ProductDTO) -> dict[str, Any]:
    return dump_dto(product)


def load_product(payload: dict[str, Any]) -> ProductDTO:
    return _load_dataclass(ProductDTO, payload)


def dump_suppliers(suppliers: list[SupplierDTO]) -> list[dict[str, Any]]:
    return [dump_dto(supplier) for supplier in suppliers]


def load_suppliers(payload: list[dict[str, Any]] | None) -> list[SupplierDTO]:
    return [
        _load_dataclass(SupplierDTO, supplier)
        for supplier in (payload or [])
    ]


def dump_profit(profit: ProfitBreakdown | Any | None) -> dict[str, Any] | None:
    if profit is None:
        return None
    if is_dataclass(profit):
        return dump_dto(profit)
    keys = [field.name for field in fields(ProfitBreakdown)]
    payload = {key: getattr(profit, key) for key in keys if hasattr(profit, key)}
    for key in ("total_cost", "net_profit", "profit_margin"):
        if hasattr(profit, key):
            payload[key] = getattr(profit, key)
    payload["schema_version"] = "1.0"
    return json_snapshot(payload)


def load_profit(payload: dict[str, Any] | None) -> ProfitBreakdown | None:
    if payload is None:
        return None
    # ProfitBreakdown has required constructor fields. Compatibility tests and
    # old snapshots may contain only derived values, so preserve those without
    # fabricating zero-valued cost evidence.
    constructor_fields = {field.name for field in fields(ProfitBreakdown)}
    values = {key: value for key, value in payload.items() if key in constructor_fields}
    try:
        return ProfitBreakdown(**values)
    except TypeError:
        return SimpleNamespace(**{key: value for key, value in payload.items() if key != "schema_version"})


def dump_market(market: MarketAnalysisDTO | Any | None) -> dict[str, Any] | None:
    if market is None:
        return None
    if is_dataclass(market):
        return dump_dto(market)
    keys = [field.name for field in fields(MarketAnalysisDTO)]
    payload = {key: getattr(market, key) for key in keys if hasattr(market, key)}
    payload["schema_version"] = "1.0"
    return json_snapshot(payload)


def load_market(payload: dict[str, Any] | None) -> MarketAnalysisDTO | None:
    return _load_dataclass(MarketAnalysisDTO, payload)


def dump_score(score: ScoreBreakdown | Any | None) -> dict[str, Any] | None:
    if score is None:
        return None
    if is_dataclass(score):
        return dump_dto(score)
    keys = [field.name for field in fields(ScoreBreakdown)]
    payload = {key: getattr(score, key) for key in keys if hasattr(score, key)}
    payload["schema_version"] = "1.0"
    return json_snapshot(payload)


def load_score(payload: dict[str, Any] | None) -> ScoreBreakdown | None:
    return _load_dataclass(ScoreBreakdown, payload)
