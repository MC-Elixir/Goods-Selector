"""
PageLike 适配器 — Amazon 字段提取的薄后端抽象

crawlers/_amazon_extractors.py 里所有提取函数都只依赖这个接口（text / text_all /
all_links / attr / table_row），具体是 Scrapling Adaptor 还是 Playwright Page
由调用方选择。

两个内建实现：
    ScraplingPage   — 包 scrapling.parser.Adaptor
    PlaywrightPage  — 包 playwright.sync_api.Page
"""
from __future__ import annotations

from typing import Optional, Protocol


class PageLike(Protocol):
    """Amazon 字段提取的最小页面接口。"""

    def text(self, selector: str) -> Optional[str]: ...
    def text_all(self, selector: str) -> list[str]: ...
    def all_links(self, selector: str) -> list[tuple[str, str]]:
        """返回 (text, href) 列表，跳过空值。"""
        ...
    def attr(self, selector: str, name: str) -> Optional[str]: ...
    def table_row(self, label: str) -> Optional[str]:
        """在 prodDetTable 里查 <th> 文本包含 label 的行，返回下一列 <td> 文本。"""
        ...


# ============================================================
# Scrapling Adaptor 适配器
# ============================================================
class ScraplingPage:
    """把 scrapling.parser.Adaptor 包成 PageLike。"""

    def __init__(self, page):
        self._p = page

    def text(self, selector: str) -> Optional[str]:
        try:
            nodes = self._p.css(selector)
            if not nodes:
                return None
            t = nodes.first.text
            return t.strip() if t else None
        except Exception:
            return None

    def text_all(self, selector: str) -> list[str]:
        try:
            return [(n.text or "").strip() for n in self._p.css(selector) if (n.text or "").strip()]
        except Exception:
            return []

    def all_links(self, selector: str) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        try:
            for el in self._p.css(selector):
                href = el.attrib.get("href", "") or ""
                try:
                    text = (el.text or "").strip()
                except Exception:
                    text = ""
                if href or text:
                    results.append((text, href))
        except Exception:
            pass
        return results

    def attr(self, selector: str, name: str) -> Optional[str]:
        try:
            nodes = self._p.css(selector)
            if not nodes:
                return None
            return nodes.first.attrib.get(name)
        except Exception:
            return None

    def table_row(self, label: str) -> Optional[str]:
        """prodDetTable 里 <th> 文本含 label 的行 → 下一列 <td> 文本（递归所有子节点）。"""
        try:
            nodes = self._p.css(
                f"table.prodDetTable th:contains('{label}')"
            )
            if not nodes:
                return None
            tr = nodes[0].parent
            if not tr:
                return None
            tds = tr.css("td")
            if not tds:
                return None
            td = tds[0]
            # 关键：td 通常含嵌套子节点（span/ul/li/...），必须递归取所有文本
            # 否则 BSR 这种 "<ul><li><span>#1 in..." 结构只能取到空白
            parts: list[str] = []
            try:
                # get_all_text(separator) 把所有后代文本节点用分隔符连起来
                joined = td.get_all_text(" ")
                if joined:
                    parts.append(joined)
            except Exception:
                pass
            if not parts:
                try:
                    t = td.text
                    if t:
                        parts.append(t)
                except Exception:
                    pass
            text = " ".join(p.strip() for p in parts if p and p.strip())
            return text if text else None
        except Exception:
            return None


# ============================================================
# Playwright Page 适配器
# ============================================================
class PlaywrightPage:
    """把 playwright.sync_api.Page 包成 PageLike。"""

    def __init__(self, page):
        self._p = page

    def text(self, selector: str) -> Optional[str]:
        try:
            el = self._p.query_selector(selector)
            if not el:
                return None
            t = el.inner_text()
            return t.strip() if t else None
        except Exception:
            return None

    def text_all(self, selector: str) -> list[str]:
        try:
            els = self._p.query_selector_all(selector) or []
            return [el.inner_text().strip() for el in els if (el.inner_text() or "").strip()]
        except Exception:
            return []

    def all_links(self, selector: str) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        try:
            els = self._p.query_selector_all(selector) or []
            for el in els:
                href = (el.get_attribute("href") or "")
                try:
                    text = (el.inner_text() or "").strip()
                except Exception:
                    text = ""
                if href or text:
                    results.append((text, href))
        except Exception:
            pass
        return results

    def attr(self, selector: str, name: str) -> Optional[str]:
        try:
            el = self._p.query_selector(selector)
            return el.get_attribute(name) if el else None
        except Exception:
            return None

    def table_row(self, label: str) -> Optional[str]:
        """Playwright 没有 :contains()，用 XPath。"""
        try:
            xpath = (
                f"xpath=//table[contains(@class,'prodDetTable')]"
                f"//th[contains(normalize-space(.),'{label}')]/following-sibling::td[1]"
            )
            el = self._p.query_selector(xpath)
            if not el:
                return None
            # Playwright 的 inner_text() 已经递归所有后代
            t = el.inner_text()
            return t.strip() if t else None
        except Exception:
            return None
