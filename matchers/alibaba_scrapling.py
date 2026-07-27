"""
1688 货源匹配 — Scrapling 路径
=================================

用 Scrapling 的 StealthyFetcher 抓 1688 搜索页。
比 Playwright 路径更轻量：
  - patchright 修补的 chromium，自带反检测
  - curl_cffi TLS 指纹伪装
  - 启动比纯 Playwright 快 ~30%

局限：
  - TMD 仍可能在多次请求后拦截（IP 行为分析）
  - 加 cookies 能撑更久，但长期仍需重登

降级链（在 matchers/__init__.py 中编排）：
  1. Alibaba1688ScraplingMatcher      ← 本文件（首选）
  2. Alibaba1688PlaywrightMatcher     ← 兜底
  3. mock                              ← 离线兜底
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from loguru import logger

from matchers.alibaba_pailitao import SupplierDTO

# ============================================================
# 常量
# ============================================================
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_COOKIES_FILE = _PROJECT_ROOT / "data" / "1688_cookies.json"

_SEARCH_BASE = "https://s.1688.com/selloffer/offer_search.htm"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def _gbk_url(keyword: str) -> str:
    return f"{_SEARCH_BASE}?keywords={quote(keyword, encoding='gbk')}"


def _load_cookie_header() -> Optional[str]:
    """把 Playwright 保存的 cookies 转成 Cookie 请求头。

    注意：1688 TMD 反爬对 HttpOnly / SameSite / JS-set cookies 全部不认，
    所以即使带了 Cookie header 也经常被 TMD 拦截（搜索页跳转到 login）。
    Playwright 路径是 1688 唯一靠谱的走法（context.add_cookies 把 cookies
    注入浏览器 cookie jar）。本函数只用于"有 cookies 至少尝试一下"的场景。
    """
    if not _COOKIES_FILE.exists():
        return None
    try:
        with open(_COOKIES_FILE, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        return "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get("name"))
    except Exception as e:
        logger.warning(f"[scrapling] 读 cookies 失败: {e}")
        return None


# ============================================================
# 卡片解析（与 alibaba_playwright.py 逻辑一致）
# ============================================================
def _card_text(card) -> str:
    try:
        nodes = card.css("::text").getall() if hasattr(card, "css") else []
    except Exception:
        nodes = []
    return "\n".join(t.strip() for t in nodes if t.strip())


def _parse_price(text: str) -> Optional[float]:
    t = (text or "").replace("\n", "").replace(" ", "")
    m = re.search(r"[¥￥]([\d,]+\.?\d*)", t)
    if not m:
        m = re.search(r"^([\d,]+\.?\d*)", re.sub(r"[^\d.,]", "", t))
    if m:
        try:
            v = float(m.group(1).replace(",", ""))
            if 0 < v <= 9999:
                return v
        except ValueError:
            pass
    return None


def _parse_monthly_sales(text: str) -> Optional[int]:
    for pattern in (
        r"全网([\d.]+)万\+?件",
        r"月销[量售]*([\d.]+)万\+?件",
        r"月成交([\d.]+)万\+?",
        r"月销[量售]*([\d,]+)",
        r"([\d,]+)\s*笔",
    ):
        m = re.search(pattern, text or "")
        if m:
            raw = m.group(1).replace(",", "")
            try:
                val = float(raw)
                if "万" in pattern:
                    return int(val * 10000)
                return int(val)
            except ValueError:
                pass
    return None


def _parse_repeat_rate(text: str) -> Optional[float]:
    m = re.search(r"回头率(\d+)%", text or "")
    if m:
        try:
            return float(m.group(1)) / 100
        except ValueError:
            pass
    return None


def _parse_moq(text: str) -> Optional[int]:
    for pattern in (
        r"起订量[：:\s]*(\d+)",
        r"最小起订[：:\s]*(\d+)",
        r"≥\s*(\d+)\s*件",
        r"最少(\d+)件",
        r"(\d+)件起",
    ):
        m = re.search(pattern, text or "")
        if m:
            return int(m.group(1))
    return 1


def _extract_supplier(text: str) -> Optional[str]:
    lines = [l.strip() for l in (text or "").split("\n") if l.strip()]
    for line in reversed(lines):
        if any(k in line for k in ("公司", "工厂", "厂家", "有限", "店")):
            return line[:40]
    return lines[-1][:40] if lines else None


def _offer_id_from_href(href: str) -> str:
    from urllib.parse import urlparse, parse_qs
    try:
        qs = parse_qs(urlparse(href).query)
        ids = qs.get("offerId", [])
        if ids:
            return ids[0]
    except Exception:
        pass
    m = re.search(r"offerId=(\d+)", href or "")
    return m.group(1) if m else ""


def _parse_card(card) -> Optional[SupplierDTO]:
    href = (card.attrib.get("href") if hasattr(card, "attrib") else "") or ""
    if not href:
        try:
            href_list = card.css("::attr(href)").getall() if hasattr(card, "css") else []
            href = href_list[0] if href_list else ""
        except Exception:
            href = ""
    offer_id = _offer_id_from_href(href)
    if not offer_id:
        return None

    full_text = _card_text(card)
    title = full_text.split("\n")[0][:60] if full_text else ""

    price_cny = _parse_price(full_text)
    price_tiers = [{"qty": 1, "price": price_cny}] if price_cny else []

    img_url: Optional[str] = None
    try:
        img_els = card.css("img")
        if img_els:
            src = img_els[0].attrib.get("src") or img_els[0].attrib.get("data-src") or ""
            if src.startswith("//"):
                src = f"https:{src}"
            img_url = src or None
    except Exception:
        pass

    return SupplierDTO(
        alibaba_offer_id=offer_id,
        supplier_name=_extract_supplier(full_text),
        offer_url=f"https://detail.1688.com/offer/{offer_id}.html",
        offer_image_url=img_url,
        moq=_parse_moq(full_text),
        base_price_cny=price_cny,
        price_tiers=price_tiers,
        monthly_sales=_parse_monthly_sales(full_text),
        repeat_buyer_rate=_parse_repeat_rate(full_text),
        is_factory="工厂" in full_text or "源头厂家" in full_text,
        title_cn=title or None,
        raw_data={"title_cn": title, "full_text": full_text[:200], "source": "alibaba_scrapling"},
    )


# ============================================================
# 主类
# ============================================================
class Alibaba1688ScraplingMatcher:
    """Scrapling 版 1688 货源匹配器（轻量 HTTP 版）。

    用 StealthyFetcher（curl_cffi TLS 伪装）+ Cookie header 传 cookies。
    对 1688 TMD 反爬效果差（很多 JS-set / HttpOnly cookies 没法用 header 传），
    但启动快、不占浏览器资源。真正好用的是同目录下的
    Alibaba1688PlaywrightMatcher（用真浏览器 + context.add_cookies 注入 cookies），
    match_suppliers 会在 Scrapling 返回空时自动降级到 Playwright。
    """

    def __init__(self, headless: bool = True, page_wait: float = 8.0):
        self.headless = headless
        self.page_wait = page_wait
        self._scrapling_available: Optional[bool] = None
        self._cookie_header: Optional[str] = _load_cookie_header()
        if self._cookie_header:
            logger.info(f"[scrapling] 已加载 cookies（{len(self._cookie_header)} 字符）")
        else:
            logger.info("[scrapling] 无 cookies，匿名模式（大概率被 TMD 拦截）")

    # ---------------- 探测依赖 ----------------
    def _ensure_scrapling(self) -> bool:
        if self._scrapling_available is False:
            return False
        if self._scrapling_available is True:
            return True
        try:
            from scrapling.fetchers import StealthyFetcher  # noqa: F401
            self._scrapling_available = True
        except Exception as e:
            logger.error(f"[scrapling] 不可用: {e}")
            self._scrapling_available = False
        return self._scrapling_available

    # ---------------- 公开 API ----------------
    def search_by_keyword(
        self,
        keywords: list[str],
        limit: int = 10,
    ) -> list[SupplierDTO]:
        if not keywords:
            return []
        if not self._ensure_scrapling():
            return []

        from scrapling.fetchers import StealthyFetcher

        seen_ids: set[str] = set()
        results: list[SupplierDTO] = []

        for kw in keywords:
            if len(results) >= limit:
                break
            try:
                extra = {"Cookie": self._cookie_header} if self._cookie_header else None
                page = StealthyFetcher.fetch(
                    _gbk_url(kw),
                    headless=self.headless,
                    stealth=True,
                    network_idle=True,
                    timeout=60_000,
                    extra_headers=extra,
                )
                # 检查是否被 TMD 拦截（跳转到 login.taobao.com）
                if "login.taobao.com" in (page.url if hasattr(page, "url") else ""):
                    logger.warning(f"[scrapling] '{kw}' 被 TMD 拦截（跳登录）")
                    continue

                # 解析产品卡片
                cards = page.css("a[href*='detail.1688.com']")
                n = len(cards) if hasattr(cards, "__len__") else 0
                logger.info(f"[scrapling] '{kw}' → {n} 条候选")

                for card in cards:
                    try:
                        dto = _parse_card(card)
                    except Exception as e:
                        logger.debug(f"[scrapling] 卡片解析失败: {e}")
                        continue
                    if dto and dto.alibaba_offer_id not in seen_ids:
                        seen_ids.add(dto.alibaba_offer_id)
                        results.append(dto)
                        if len(results) >= limit:
                            break
            except Exception as e:
                logger.warning(f"[scrapling] '{kw}' 失败: {e}")
                continue

        results.sort(key=lambda d: d.monthly_sales or 0, reverse=True)
        logger.info(f"[scrapling] 共 {len(results)} 条")
        return results[:limit]

    def search_by_image(self, image_url: str, keywords: Optional[list[str]] = None, limit: int = 10) -> list[SupplierDTO]:
        """图搜：Scrapling 暂未实现图搜，关键词搜索兜底。"""
        logger.info("[scrapling] 图搜未实现，降级为关键词搜索")
        return self.search_by_keyword(keywords or [], limit=limit)
