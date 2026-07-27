"""Supported Amazon US category choices for the local WebUI."""
from __future__ import annotations

from typing import Any


AMAZON_US_CATEGORIES: tuple[dict[str, str], ...] = (
    {"canonical": "Home & Kitchen", "label_zh": "家居厨具", "label_en": "Home & Kitchen"},
    {"canonical": "Kitchen & Dining", "label_zh": "厨房餐饮", "label_en": "Kitchen & Dining"},
    {"canonical": "Sports & Outdoors", "label_zh": "运动户外", "label_en": "Sports & Outdoors"},
    {"canonical": "Pet Supplies", "label_zh": "宠物用品", "label_en": "Pet Supplies"},
    {"canonical": "Toys & Games", "label_zh": "玩具游戏", "label_en": "Toys & Games"},
    {"canonical": "Office Products", "label_zh": "办公用品", "label_en": "Office Products"},
)


def list_categories() -> list[dict[str, Any]]:
    return [dict(item) for item in AMAZON_US_CATEGORIES]


def canonical_category(value: str) -> str:
    wanted = (value or "").strip()
    for item in AMAZON_US_CATEGORIES:
        if wanted in {item["canonical"], item["label_zh"], item["label_en"]}:
            return item["canonical"]
    raise ValueError("category must be one of the supported Amazon US categories")
