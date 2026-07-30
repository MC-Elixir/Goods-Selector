"""
Amazon cookies 持久化
======================

把 StealthySession / Playwright 的 cookies 存到 data/amazon_cookies.json，
下次跑时直接复用——能显著降低 captcha 触发概率。

文件格式：Playwright 原生 cookies 列表（与 1688_cookies.json 一致）：

    [
      {"name": "session-id", "value": "...",
       "domain": ".amazon.com", "path": "/", "expires": ..., ...},
      ...
    ]

写入采用 temp + rename 原子操作，避免半截文件。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from loguru import logger

_DEFAULT_COOKIE_PATH = Path("data") / "amazon_cookies.json"


def cookie_path(custom_path: Optional[Path] = None) -> Path:
    """返回 cookies 文件路径。"""
    return custom_path or _DEFAULT_COOKIE_PATH


def load_cookies(path: Optional[Path] = None) -> Optional[list[dict]]:
    """从 JSON 文件读 cookies。文件不存在 / 解析失败返回 None。"""
    p = cookie_path(path)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            logger.warning(f"[cookies] {p} 格式异常（期望 list）")
            return None
        # 过滤掉缺 name 的脏数据
        cleaned = [c for c in data if isinstance(c, dict) and c.get("name")]
        logger.info(f"[cookies] 从 {p} 读入 {len(cleaned)} 个 cookies")
        return cleaned
    except Exception as e:
        logger.warning(f"[cookies] 读 {p} 失败: {e}")
        return None


def save_cookies(
    cookies: list[dict],
    path: Optional[Path] = None,
) -> Optional[Path]:
    """原子写入 cookies 到 JSON 文件。返回写入的路径；失败返回 None。"""
    p = cookie_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        # 在同一目录建临时文件（确保 os.replace 是原子的）
        fd, tmp = tempfile.mkstemp(
            prefix=f".{p.name}.",
            suffix=".tmp",
            dir=str(p.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)
            logger.info(f"[cookies] 保存 {len(cookies)} 个 cookies 到 {p}")
            return p
        except Exception:
            # 失败时清理临时文件
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.warning(f"[cookies] 写 {p} 失败: {e}")
        return None


def clear_cookies(path: Optional[Path] = None) -> bool:
    """删除 cookies 文件。返回是否成功删除。"""
    p = cookie_path(path)
    try:
        if p.exists():
            p.unlink()
            logger.info(f"[cookies] 已删除 {p}")
        return True
    except OSError as e:
        logger.warning(f"[cookies] 删除 {p} 失败: {e}")
        return False
