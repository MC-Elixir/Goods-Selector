"""
Amazon cache 模块单测

使用 set_cache_root 把缓存根重定向到 tmp_path，避开污染用户目录。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from crawlers import _amazon_cache as cache


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path):
    """每个测试把 cache root 指向 tmp_path。"""
    cache.set_cache_root(tmp_path / "cache_amazon")
    yield
    cache.close_cache()


# ============================================================
# get/set/delete
# ============================================================
class TestGetSet:
    def test_miss_returns_none(self):
        assert cache.get_html("any:key") is None

    def test_set_then_get(self):
        cache.set_html("foo", "<html>bar</html>")
        assert cache.get_html("foo") == "<html>bar</html>"

    def test_overwrite(self):
        cache.set_html("foo", "v1")
        cache.set_html("foo", "v2")
        assert cache.get_html("foo") == "v2"

    def test_delete(self):
        cache.set_html("foo", "v1")
        assert cache.delete("foo") is True
        assert cache.get_html("foo") is None


# ============================================================
# 开关
# ============================================================
class TestEnableCacheFlag:
    def test_disabled_skips_writes_and_reads(self, monkeypatch):
        cache.set_html("foo", "v1")
        assert cache.get_html("foo") == "v1"

        # 关闭后所有写被忽略、所有读直接返回 None
        monkeypatch.setattr(cache.settings, "enable_api_cache", False, raising=False)
        cache.set_html("bar", "v2")
        assert cache.get_html("bar") is None
        assert cache.get_html("foo") is None  # 之前写入的也不可见


# ============================================================
# Key 构造
# ============================================================
class TestKeys:
    def test_detail_key_includes_marketplace(self):
        assert cache.detail_key("B0ABC", "US") == "detail:US:B0ABC"
        assert cache.detail_key("B0ABC", "JP") == "detail:JP:B0ABC"

    def test_bsr_key_includes_page(self):
        k1 = cache.bsr_key("home-garden", 1, "US")
        k2 = cache.bsr_key("home-garden", 2, "US")
        assert k1 != k2
        assert "home-garden" in k1
        assert ":1" in k1
        assert ":2" in k2

    def test_bsr_key_includes_marketplace(self):
        assert cache.bsr_key("home-garden", 1, "DE") == "bsr:DE:home-garden:1"


# ============================================================
# stats
# ============================================================
class TestStats:
    def test_empty_cache(self):
        s = cache.stats()
        assert s["entries"] == 0

    def test_after_writes(self):
        cache.set_html("a", "1")
        cache.set_html("b", "2")
        s = cache.stats()
        assert s["entries"] == 2
        assert s["size_bytes"] > 0
