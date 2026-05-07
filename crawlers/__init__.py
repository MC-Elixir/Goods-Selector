"""Amazon Best Seller 数据采集层。

后端选项（backend 参数）：
    playwright  — 无需 API Key，Playwright 爬虫（默认，仅需 Anthropic Key）
    keepa       — Keepa API，$19/月，数据最全（需 KEEPA_API_KEY）
    rainforest  — Rainforest API，按次计费（需 RAINFOREST_API_KEY）
    auto        — 自动选择：有 Key 用 API，无 Key 用 playwright

统一接口：
    from crawlers.amazon_bsr import crawl_best_sellers, ProductDTO
"""
