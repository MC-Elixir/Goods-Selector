"""链路测试脚本：测试 Amazon 选品 → 1688 供应商 → 利润模型 → 评分系统"""
from __future__ import annotations

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger

# 配置日志
logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<7} | {message}")


def test_amazon_crawler():
    """测试 Amazon 爬虫（Stage 1）"""
    logger.info("=" * 60)
    logger.info("Stage 1: 测试 Amazon 爬虫")
    logger.info("=" * 60)

    from crawlers.amazon_playwright import AmazonPlaywrightScraper

    scraper = AmazonPlaywrightScraper(headless=True)
    products = scraper.scrape_best_sellers("Home & Kitchen", limit=3, marketplace="US")

    logger.info(f"爬取到 {len(products)} 个产品")
    for p in products:
        logger.info(f"  - {p.asin}: {p.title[:50]}... | ${p.price} | BSR#{p.bsr_rank}")

    return products


def test_1688_matcher(products):
    """测试 1688 供应商匹配（Stage 2）"""
    logger.info("\n" + "=" * 60)
    logger.info("Stage 2: 测试 1688 供应商匹配")
    logger.info("=" * 60)

    from matchers.alibaba_playwright import Alibaba1688PlaywrightMatcher
    from matchers import match_suppliers

    all_records = []
    for product in products:
        logger.info(f"\n匹配产品: {product.asin} - {product.title[:40]}...")
        try:
            suppliers = match_suppliers(product)
            logger.info(f"  找到 {len(suppliers)} 个供应商")
            for s in suppliers[:3]:  # 只显示前3个
                logger.info(f"    - {s.supplier_name}: ¥{s.base_price_cny} | 月销{s.monthly_sales}")
            all_records.append({"product": product, "suppliers": suppliers})
        except Exception as e:
            logger.warning(f"  匹配失败: {e}")
            all_records.append({"product": product, "suppliers": []})

    return all_records


def test_profit_model(records):
    """测试利润模型（Stage 3）"""
    logger.info("\n" + "=" * 60)
    logger.info("Stage 3: 测试利润模型")
    logger.info("=" * 60)

    from analyzers.profit_model import predict_profit

    for rec in records:
        product = rec["product"]
        suppliers = rec["suppliers"]
        if not suppliers:
            logger.info(f"\n{product.asin}: 无供应商，跳过利润计算")
            continue

        best_supplier = suppliers[0]  # 取第一个（销量最高）
        logger.info(f"\n产品: {product.asin} - {product.title[:40]}...")
        logger.info(f"  售价: ${product.price}")
        logger.info(f"  供应商: {best_supplier.supplier_name} | 采购价: ¥{best_supplier.base_price_cny}")

        try:
            profit = predict_profit(product, best_supplier)
            logger.info(f"  ──────────────────────────────────")
            logger.info(f"  采购成本: ${profit.purchase_cost:.2f}")
            logger.info(f"  头程物流: ${profit.shipping_cost:.2f}")
            logger.info(f"  FBA费用: ${profit.fba_fee:.2f}")
            logger.info(f"  平台佣金: ${profit.commission:.2f}")
            logger.info(f"  广告费: ${profit.ad_cost:.2f}")
            logger.info(f"  退货损耗: ${profit.return_loss:.2f}")
            logger.info(f"  汇率损耗: ${profit.exchange_loss:.2f}")
            logger.info(f"  ──────────────────────────────────")
            logger.info(f"  净利润: ${profit.net_profit:.2f} | 净利率: {profit.profit_margin:.1%}")
            rec["profit"] = profit
        except Exception as e:
            logger.warning(f"  利润计算失败: {e}")
            rec["profit"] = None

    return records


def test_scorer(records):
    """测试评分系统（Stage 5）"""
    logger.info("\n" + "=" * 60)
    logger.info("Stage 5: 测试评分系统")
    logger.info("=" * 60)

    from analyzers.scorer import score_product

    for rec in records:
        product = rec["product"]
        profit = rec.get("profit")
        suppliers = rec.get("suppliers", [])

        if not profit:
            logger.info(f"\n{product.asin}: 无利润数据，跳过评分")
            rec["score"] = None
            continue

        logger.info(f"\n产品: {product.asin} - {product.title[:40]}...")
        try:
            score = score_product(
                product=product,
                profit_breakdown=profit,
                market_analysis=None,  # 跳过卖家精灵
                suppliers=suppliers,
            )
            logger.info(f"  ──────────────────────────────────")
            logger.info(f"  利润得分: {score.profit_score:.2f}")
            logger.info(f"  需求得分: {score.demand_score:.2f}")
            logger.info(f"  竞争得分: {score.competition_score:.2f}")
            logger.info(f"  供应得分: {score.supply_score:.2f}")
            logger.info(f"  物流得分: {score.logistics_score:.2f}")
            logger.info(f"  风险得分: {score.risk_score:.2f}")
            logger.info(f"  ──────────────────────────────────")
            logger.info(f"  综合得分: {score.total_score:.1f}/100")
            logger.info(f"  通过硬性筛选: {'✓' if score.passed_hard_filter else '✗'}")
            if score.rejection_reasons:
                logger.info(f"  拒绝原因: {', '.join(score.rejection_reasons)}")
            rec["score"] = score
        except Exception as e:
            logger.warning(f"  评分失败: {e}")
            rec["score"] = None

    return records


def test_export(records):
    """测试报告导出（Stage 7）"""
    logger.info("\n" + "=" * 60)
    logger.info("Stage 7: 测试报告导出")
    logger.info("=" * 60)

    from pipeline.orchestrator import PipelineRecord
    from reports.exporter import export_excel, export_markdown, export_json

    # 转换为 PipelineRecord 格式
    pipeline_records = []
    for rec in records:
        pr = PipelineRecord(
            product=rec["product"],
            suppliers=rec.get("suppliers", []),
            profit=rec.get("profit"),
            market=None,
            score=rec.get("score"),
        )
        pipeline_records.append(pr)

    try:
        export_excel(pipeline_records)
        logger.info("✓ Excel 导出成功")
    except Exception as e:
        logger.warning(f"✗ Excel 导出失败: {e}")

    try:
        export_markdown(pipeline_records)
        logger.info("✓ Markdown 导出成功")
    except Exception as e:
        logger.warning(f"✗ Markdown 导出失败: {e}")

    try:
        export_json(pipeline_records)
        logger.info("✓ JSON 导出成功")
    except Exception as e:
        logger.warning(f"✗ JSON 导出失败: {e}")


def main():
    logger.info("开始链路测试")
    logger.info("测试目标: Amazon 选品 → 1688 供应商 → 利润模型 → 评分 → 导出")
    logger.info("注意: 跳过卖家精灵 API (Stage 4)\n")

    try:
        # Stage 1: Amazon 爬虫
        products = test_amazon_crawler()
        if not products:
            logger.error("Amazon 爬虫未返回产品，测试终止")
            return

        # Stage 2: 1688 供应商匹配
        records = test_1688_matcher(products)

        # Stage 3: 利润模型
        records = test_profit_model(records)

        # Stage 5: 评分系统（跳过 Stage 4 卖家精灵）
        records = test_scorer(records)

        # Stage 7: 报告导出
        test_export(records)

        # 汇总
        logger.info("\n" + "=" * 60)
        logger.info("测试汇总")
        logger.info("=" * 60)
        logger.info(f"产品数量: {len(records)}")
        logger.info(f"有供应商: {sum(1 for r in records if r.get('suppliers'))}")
        logger.info(f"有利润数据: {sum(1 for r in records if r.get('profit'))}")
        logger.info(f"有评分数据: {sum(1 for r in records if r.get('score'))}")

        passed = sum(1 for r in records if r.get("score") and r["score"].passed_hard_filter)
        logger.info(f"通过硬性筛选: {passed}")

        logger.info("\n✓ 链路测试完成!")

    except Exception as e:
        logger.exception(f"测试失败: {e}")
        raise


if __name__ == "__main__":
    main()
