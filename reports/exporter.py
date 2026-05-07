"""
报告导出
========

输出三种产物：
    1. Excel 候选选品表    .xlsx，每个产品一行 + 评分明细
    2. Markdown 详情报告   每个产品一份 .md，包含图片、链接、评分原因
    3. JSON                便于下游程序消费
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def export_excel(candidates: list, output_path: Optional[Path] = None) -> Path:
    """导出候选池为 Excel。"""
    raise NotImplementedError


def export_markdown(candidates: list, output_dir: Optional[Path] = None) -> list[Path]:
    """每个候选品导出一份 .md。"""
    raise NotImplementedError


def export_json(candidates: list, output_path: Optional[Path] = None) -> Path:
    """导出 JSON。"""
    raise NotImplementedError
