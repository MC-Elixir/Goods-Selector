from __future__ import annotations

import time
from dataclasses import asdict

from crawlers.amazon_bsr import ProductDTO
from matchers import alibaba_result_cache as cache
from matchers.alibaba_pailitao import SupplierDTO


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


def _rejected_supplier() -> SupplierDTO:
    return SupplierDTO(
        alibaba_offer_id="780485617590",
        offer_url="https://detail.1688.com/offer/780485617590.html",
        base_price_cny=12.5,
        moq=10,
        match_quality_score=0.31,
        match_verification_method="heuristic_rejected",
    )


def _low_quality_supplier() -> SupplierDTO:
    return SupplierDTO(
        alibaba_offer_id="780485617591",
        offer_url="https://detail.1688.com/offer/780485617591.html",
        base_price_cny=12.5,
        moq=10,
        match_quality_score=0.20,
        match_verification_method="heuristic",
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


def test_rejected_supplier_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_CACHE_FILE", tmp_path / "real_supplier_results.json")

    key = cache.make_cache_key(_product(), ["keyword"], top_k=5)
    cache.save_cached_suppliers(key, [_rejected_supplier()])

    assert cache.load_cached_suppliers(key, ttl_seconds=3600) == []


def test_low_quality_supplier_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_CACHE_FILE", tmp_path / "real_supplier_results.json")

    key = cache.make_cache_key(_product(), ["keyword"], top_k=5)
    cache.save_cached_suppliers(key, [_low_quality_supplier()])

    assert cache.load_cached_suppliers(key, ttl_seconds=3600) == []


def test_legacy_rejected_cache_entry_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_CACHE_FILE", tmp_path / "real_supplier_results.json")

    key = cache.make_cache_key(_product(), ["keyword"], top_k=5)
    cache._write_json(
        cache._CACHE_FILE,
        {
            key: {
                "created_at": time.time(),
                "suppliers": [asdict(_rejected_supplier())],
            },
        },
    )

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


def test_offer_detail_cache_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_DETAIL_CACHE_FILE", tmp_path / "offer_details.json")

    cache.save_cached_offer_detail("780485617589", {"moq": 20, "delivery_days": 7})

    assert cache.load_cached_offer_detail("780485617589", ttl_seconds=3600) == {
        "moq": 20,
        "delivery_days": 7,
    }


def test_offer_detail_cache_respects_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_DETAIL_CACHE_FILE", tmp_path / "offer_details.json")
    cache.save_cached_offer_detail("780485617589", {"moq": 20})

    assert cache.load_cached_offer_detail("780485617589", ttl_seconds=0) == {}


def test_offer_detail_cache_records_freshness_schema_and_blocked_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_DETAIL_CACHE_FILE", tmp_path / "offer_details.json")
    cache.save_cached_offer_detail("780485617589", {"moq": 20}, ttl_seconds=60)

    entry = cache._read_json(cache._DETAIL_CACHE_FILE, {})["780485617589"]
    assert entry["schema_version"] == cache.DETAIL_CACHE_SCHEMA_VERSION
    assert entry["blocked"] is False
    assert entry["observed_at"] <= entry["expires_at"]


def test_offer_detail_cache_rejects_expired_or_wrong_schema_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_DETAIL_CACHE_FILE", tmp_path / "offer_details.json")
    now = time.time()
    cache._write_json(cache._DETAIL_CACHE_FILE, {
        "expired": {"schema_version": cache.DETAIL_CACHE_SCHEMA_VERSION, "blocked": False,
                    "observed_at": now - 100, "expires_at": now - 1, "detail": {"moq": 20}},
        "wrong": {"schema_version": -1, "blocked": False,
                  "observed_at": now, "expires_at": now + 100, "detail": {"moq": 20}},
        "blocked": {"schema_version": cache.DETAIL_CACHE_SCHEMA_VERSION, "blocked": True,
                    "observed_at": now, "expires_at": now + 100, "detail": {"moq": 20}},
    })
    assert cache.load_cached_offer_detail("expired", ttl_seconds=3600) == {}
    assert cache.load_cached_offer_detail("wrong", ttl_seconds=3600) == {}
    assert cache.load_cached_offer_detail("blocked", ttl_seconds=3600) == {}
