from __future__ import annotations

import time

from crawlers.amazon_bsr import ProductDTO
from matchers.alibaba_pailitao import SupplierDTO
from matchers import alibaba_result_cache as cache


def _product() -> ProductDTO:
    return ProductDTO(
        asin="B0TEST1688",
        marketplace="US",
        title="Test Product",
        main_image_url="https://example.com/image.jpg",
    )


def _real_supplier() -> SupplierDTO:
    return SupplierDTO(
        alibaba_offer_id="780485617589",
        offer_url="https://detail.1688.com/offer/780485617589.html",
        base_price_cny=12.5,
        moq=10,
        match_verification_method="heuristic",
    )


def _mock_supplier() -> SupplierDTO:
    return SupplierDTO(
        alibaba_offer_id="abcdef123456",
        offer_url="https://detail.1688.com/offer/abcdef123456.html",
        match_verification_method="mock",
    )


def test_cache_round_trip_real_supplier(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_CACHE_FILE", tmp_path / "real_supplier_results.json")

    key = cache.make_cache_key(_product(), ["keyword"], top_k=5)
    cache.save_cached_suppliers(key, [_real_supplier()])

    loaded = cache.load_cached_suppliers(key, ttl_seconds=3600)
    assert len(loaded) == 1
    assert loaded[0].alibaba_offer_id == "780485617589"
    assert loaded[0].base_price_cny == 12.5


def test_mock_supplier_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_CACHE_FILE", tmp_path / "real_supplier_results.json")

    key = cache.make_cache_key(_product(), ["keyword"], top_k=5)
    cache.save_cached_suppliers(key, [_mock_supplier()])

    assert cache.load_cached_suppliers(key, ttl_seconds=3600) == []


def test_cache_ttl_expired_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_CACHE_FILE", tmp_path / "real_supplier_results.json")

    key = cache.make_cache_key(_product(), ["keyword"], top_k=5)
    cache.save_cached_suppliers(key, [_real_supplier()])

    assert cache.load_cached_suppliers(key, ttl_seconds=0) == []


def test_circuit_breaker_opens_and_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_CIRCUIT_FILE", tmp_path / "circuit_breaker.json")

    cache.open_circuit(cooldown_seconds=30, reason="blocked")
    assert cache.circuit_is_open() is True

    cache._write_json(
        cache._CIRCUIT_FILE,
        {"blocked_until": time.time() - 1, "reason": "expired"},
    )
    assert cache.circuit_is_open() is False
