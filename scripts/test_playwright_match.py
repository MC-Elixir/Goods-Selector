"""
Playwright 路径烟测
==================

不依赖官方 1688 API。直接测：
  1. Alibaba1688PlaywrightMatcher.search_by_keyword() 真实拉 1688
  2. match_suppliers() 走降级链（mock 一个 ProductDTO 触发整条路径）

跑法：PYTHONIOENCODING=utf-8 py scripts/test_playwright_match.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger  # noqa: E402

logger.remove()
logger.add(sys.stderr, level="INFO", format="<g>{time:HH:mm:ss}</g> | {level: <7} | {message}")


# ============== Part 1: 直接调 matcher 搜关键词 ==============

def test_keyword_search():
    from matchers.alibaba_playwright import Alibaba1688PlaywrightMatcher

    print("\n" + "=" * 70)
    print("Part 1: Alibaba1688PlaywrightMatcher.search_by_keyword")
    print("=" * 70)

    matcher = Alibaba1688PlaywrightMatcher(headless=True, page_wait=8)
    keywords = ["保温杯", "不锈钢水杯"]

    print(f"关键词: {keywords}")
    t0 = time.time()
    results = matcher.search_by_keyword(keywords, limit=10)
    elapsed = time.time() - t0

    print(f"\n耗时: {elapsed:.1f}s")
    print(f"返回: {len(results)} 条")
    if not results:
        print("⚠️  无结果。可能原因:")
        print("  - cookies 已过期（需重跑 setup_1688_login.py）")
        print("  - 1688 跳转了登录页 / 风控")
        print("  - 网络/代理问题")
        return False

    # 打印前 5 条
    for i, s in enumerate(results[:5], 1):
        print(f"\n  [{i}] offerId={s.alibaba_offer_id}")
        print(f"      title_cn = {s.title_cn!r}")
        print(f"      supplier = {s.supplier_name!r}")
        print(f"      moq      = {s.moq}")
        print(f"      price    = {s.base_price_cny} CNY")
        print(f"      monthly  = {s.monthly_sales}")
        print(f"      url      = {s.offer_url}")
    return True


# ============== Part 2: 走 match_suppliers 整条降级链 ==============

def test_match_suppliers():
    from crawlers.amazon_bsr import ProductDTO
    from matchers import match_suppliers

    print("\n" + "=" * 70)
    print("Part 2: match_suppliers() 整条降级链")
    print("=" * 70)

    # 模拟一个 Amazon 产品（保温杯）
    product = ProductDTO(
        asin="B0TESTING01",
        title="Stainless Steel Insulated Water Bottle 24oz",
        url="https://www.amazon.com/dp/B0TESTING01",
        main_image_url="https://m.media-amazon.com/images/I/test.jpg",
        price_usd=19.99,
        bsr_rank=1500,
        category="Home & Kitchen",
        weight_kg=0.4,
        length_cm=8.0,
        width_cm=8.0,
        height_cm=25.0,
    )

    print(f"模拟 Amazon 产品: {product.title}")
    print(f"主图 URL: {product.main_image_url}")
    t0 = time.time()
    try:
        results = match_suppliers(product, top_k=10)
    except Exception as e:
        print(f"❌ match_suppliers 抛错: {e}")
        return False
    elapsed = time.time() - t0

    print(f"\n耗时: {elapsed:.1f}s")
    print(f"返回: {len(results)} 条（已验证）")
    if not results:
        print("⚠️  无结果")
        return False

    for i, s in enumerate(results[:5], 1):
        print(f"\n  [{i}] {s.alibaba_offer_id} | {s.title_cn or '(no title)'}")
        print(f"      验证方式: {s.match_verification_method}, 质量: {s.match_quality_score}")
        print(f"      MOQ {s.moq} | 单价 {s.base_price_cny} CNY | 月销 {s.monthly_sales}")
    return True


if __name__ == "__main__":
    print("1688 Playwright 兜底路径烟测\n")
    ok1 = test_keyword_search()
    ok2 = test_match_suppliers() if ok1 else False

    print("\n" + "=" * 70)
    print("总结")
    print("=" * 70)
    print(f"Part 1 (关键词搜索) : {'✅' if ok1 else '❌'}")
    print(f"Part 2 (整条流水线) : {'✅' if ok2 else '❌'}")
    sys.exit(0 if (ok1 and ok2) else 1)
