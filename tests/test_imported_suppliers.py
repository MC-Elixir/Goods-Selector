"""Imported 1688 Open Platform payload tests."""
from __future__ import annotations

import json

from matchers import imported_suppliers
from matchers.imported_suppliers import (
    find_imported_suppliers,
    import_alibaba_supplier_payload,
    list_imported_suppliers,
)


def test_import_alibaba_supplier_payload_persists_and_searches(monkeypatch, tmp_path):
    monkeypatch.setattr(imported_suppliers, "_IMPORT_FILE", tmp_path / "imports.json")
    payload = {
        "success": True,
        "result": {
            "productList": [
                {
                    "productId": 123456789,
                    "subject": "304不锈钢保温杯 700ml",
                    "productInfo": {"mainPictUrl": "https://img.example/a.jpg"},
                    "saleInfo": {"minOrderQuantity": "20", "priceRangeList": [{"startQuantity": 50, "price": "22"}]},
                    "supplierInfo": {"supplierName": "宁波源头工厂", "isFactory": True},
                    "tradeInfo": {"monthlyOrderNum": "1200"},
                }
            ]
        },
    }

    result = import_alibaba_supplier_payload(json.dumps(payload, ensure_ascii=False), keyword="保温杯", note="api test")
    listed = list_imported_suppliers()
    found = find_imported_suppliers(["保温杯"], top_k=5)

    assert result["imported"] == 1
    assert result["total"] == 1
    assert listed["count"] == 1
    assert found[0].alibaba_offer_id == "123456789"
    assert found[0].supplier_name == "宁波源头工厂"
    assert found[0].raw_data["source"] == "alibaba_import"
    assert found[0].raw_data["import_keyword"] == "保温杯"


def test_import_supplier_like_list_generates_stable_id(monkeypatch, tmp_path):
    monkeypatch.setattr(imported_suppliers, "_IMPORT_FILE", tmp_path / "imports.json")

    result = import_alibaba_supplier_payload(
        [{"title": "硅胶厨房垫", "supplierName": "义乌工厂", "price": "5.5", "moq": "100"}],
        keyword="厨房垫",
    )
    found = find_imported_suppliers(["厨房垫"], top_k=5)

    assert result["imported"] == 1
    assert found[0].alibaba_offer_id.startswith("import-")
    assert found[0].base_price_cny == 5.5
    assert found[0].moq == 100


def test_find_imported_suppliers_ignores_unrelated_candidates_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(imported_suppliers, "_IMPORT_FILE", tmp_path / "imports.json")
    import_alibaba_supplier_payload(
        [{"title": "304不锈钢保温杯 700ml", "supplierName": "宁波源头工厂"}],
        keyword="保温杯",
    )

    assert find_imported_suppliers(["瑜伽垫"], top_k=5) == []

    fallback = find_imported_suppliers(["瑜伽垫"], top_k=5, allow_recent_fallback=True)
    assert fallback[0].supplier_name == "宁波源头工厂"


def test_find_imported_suppliers_uses_category_aliases(monkeypatch, tmp_path):
    monkeypatch.setattr(imported_suppliers, "_IMPORT_FILE", tmp_path / "imports.json")
    import_alibaba_supplier_payload(
        [{"title": "304不锈钢保温杯 700ml", "supplierName": "宁波源头工厂"}],
        keyword="保温杯",
    )

    found = find_imported_suppliers(["水杯"], top_k=5)

    assert found[0].supplier_name == "宁波源头工厂"
