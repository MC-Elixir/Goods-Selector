"""
Amazon 抓取缓存（diskcache）
==============================

对 Amazon 详情页和 BSR 列表页的 HTML 响应做 24h TTL 文件缓存。
同一 ASIN / 同一 BSR 列表页一天内不重复请求——回放 / 调参 / 多市场切换时显著加速。

设计：
    * 缓存的是原始 HTML 字符串（不是 Adaptor — Adaptor 不可序列化）
    * key 包含 marketplace，避免 US/UK/DE/JP 串味
    * TTL 走 settings.cache_ttl_seconds（默认 24h）
    * 单例 Cache 对象（diskcache 内部用 fcntl flock，跨进程安全）
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from diskcache import Cache

from config.settings import settings


# 缓存目录：data/cache/amazon/
# 模块级可变变量，测试时可整体替换
_cache_root: Path = settings.cache_dir / "amazon"


def set_cache_root(path: Path) -> None:
    """覆盖缓存根目录（主要用于测试）。会顺手 close 旧 cache。"""
    global _cache_root
    close_cache()
    _cache_root = Path(path)
    _cache_root.mkdir(parents=True, exist_ok=True)


def cache_dir() -> Path:
    _cache_root.mkdir(parents=True, exist_ok=True)
    return _cache_root


# 全局单例
_cache: Optional[Cache] = None


def _get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = Cache(str(cache_dir()))
    return _cache


def close_cache() -> None:
    """关闭 cache（测试 / 程序退出时调用）。"""
    global _cache
    if _cache is not None:
        _cache.close()
        _cache = None


# ============================================================
# Key 构造
# ============================================================
def detail_key(asin: str, marketplace: str = "US") -> str:
    return f"detail:{marketplace}:{asin}"


def bsr_key(slug: str, page: int, marketplace: str = "US") -> str:
    return f"bsr:{marketplace}:{slug}:{page}"


# ============================================================
# 读写接口
# ============================================================
def get_html(key: str) -> Optional[str]:
    """取缓存的 HTML。返回 None = miss。"""
    if not settings.enable_api_cache:
        return None
    try:
        return _get_cache().get(key)
    except Exception:
        return None


def set_html(key: str, html: str, ttl: Optional[int] = None) -> None:
    """写 HTML 到缓存。ttl 默认 settings.cache_ttl_seconds。"""
    if not settings.enable_api_cache:
        return
    expire = ttl if ttl is not None else settings.cache_ttl_seconds
    try:
        _get_cache().set(key, html, expire=expire)
    except Exception:
        # 缓存写失败不应阻断抓取
        pass


def delete(key: str) -> bool:
    """删除单条缓存（用于 captcha 命中后强制重抓）。"""
    try:
        return bool(_get_cache().delete(key))
    except Exception:
        return False


def stats() -> dict:
    """返回缓存统计（条数、占用大小）。用于 /status 接口。"""
    try:
        c = _get_cache()
        return {
            "entries": len(c),
            "size_bytes": c.volume(),
        }
    except Exception:
        return {"entries": 0, "size_bytes": 0}
