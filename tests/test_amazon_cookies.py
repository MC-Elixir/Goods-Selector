"""
Amazon cookies 模块单测
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from crawlers import _amazon_cookies as cookies


@pytest.fixture
def tmp_cookie_path(tmp_path: Path) -> Path:
    return tmp_path / "amazon_cookies.json"


# ============================================================
# load_cookies
# ============================================================
class TestLoadCookies:
    def test_missing_file_returns_none(self, tmp_cookie_path: Path):
        assert cookies.load_cookies(tmp_cookie_path) is None

    def test_valid_file(self, tmp_cookie_path: Path):
        data = [
            {"name": "session-id", "value": "abc", "domain": ".amazon.com", "path": "/"},
            {"name": "ubid-main", "value": "xyz", "domain": ".amazon.com", "path": "/"},
        ]
        tmp_cookie_path.write_text(json.dumps(data), encoding="utf-8")
        loaded = cookies.load_cookies(tmp_cookie_path)
        assert loaded == data

    def test_corrupt_json_returns_none(self, tmp_cookie_path: Path):
        tmp_cookie_path.write_text("not json{{{", encoding="utf-8")
        assert cookies.load_cookies(tmp_cookie_path) is None

    def test_wrong_format_returns_none(self, tmp_cookie_path: Path):
        tmp_cookie_path.write_text(json.dumps({"oops": "not a list"}), encoding="utf-8")
        assert cookies.load_cookies(tmp_cookie_path) is None

    def test_filters_out_cookies_without_name(self, tmp_cookie_path: Path):
        data = [
            {"name": "session-id", "value": "abc"},
            {"value": "no-name"},          # 应被过滤
            "not a dict",                  # 应被过滤
        ]
        tmp_cookie_path.write_text(json.dumps(data), encoding="utf-8")
        loaded = cookies.load_cookies(tmp_cookie_path)
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0]["name"] == "session-id"


# ============================================================
# save_cookies — 原子写
# ============================================================
class TestSaveCookies:
    def test_creates_file_and_parent_dirs(self, tmp_path: Path):
        p = tmp_path / "subdir" / "not-yet-exists" / "cookies.json"
        data = [{"name": "a", "value": "1", "domain": ".amazon.com", "path": "/"}]
        result = cookies.save_cookies(data, p)
        assert result == p
        assert p.exists()
        assert json.loads(p.read_text(encoding="utf-8")) == data

    def test_overwrites_existing(self, tmp_cookie_path: Path):
        tmp_cookie_path.write_text("[]", encoding="utf-8")
        new_data = [{"name": "x", "value": "y"}]
        cookies.save_cookies(new_data, tmp_cookie_path)
        assert json.loads(tmp_cookie_path.read_text(encoding="utf-8")) == new_data

    def test_no_leftover_temp_files(self, tmp_cookie_path: Path):
        data = [{"name": "a", "value": "1"}]
        cookies.save_cookies(data, tmp_cookie_path)
        # 目录里只有目标文件，不应有 .tmp
        leftovers = list(tmp_cookie_path.parent.glob(f".{tmp_cookie_path.name}.*.tmp"))
        assert leftovers == []

    def test_unicode_preserved(self, tmp_cookie_path: Path):
        data = [{"name": "locale", "value": "中文"}]
        cookies.save_cookies(data, tmp_cookie_path)
        loaded = cookies.load_cookies(tmp_cookie_path)
        assert loaded[0]["value"] == "中文"


# ============================================================
# clear_cookies
# ============================================================
class TestClearCookies:
    def test_existing_file_deleted(self, tmp_cookie_path: Path):
        tmp_cookie_path.write_text("[]", encoding="utf-8")
        assert cookies.clear_cookies(tmp_cookie_path) is True
        assert not tmp_cookie_path.exists()

    def test_missing_file_is_ok(self, tmp_cookie_path: Path):
        assert cookies.clear_cookies(tmp_cookie_path) is True


# ============================================================
# 默认路径
# ============================================================
class TestDefaultPath:
    def test_default_path_is_relative(self):
        p = cookies.cookie_path()
        assert p.name == "amazon_cookies.json"
        assert "data" in p.parts
