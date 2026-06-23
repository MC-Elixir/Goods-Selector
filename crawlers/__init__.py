"""Amazon Best Seller 数据采集层。

后端选项（backend 参数）：
    scrapling  — Scrapling StealthySession（默认推荐，patchright 抗检测，无需 API Key）
    playwright — 老的 Playwright 爬虫实现
    keepa      — Keepa API，$19/月，数据最全（需 KEEPA_API_KEY）
    rainforest — Rainforest API，按次计费（需 RAINFOREST_API_KEY）
    auto       — 自动选择：scrapling → keepa → rainforest → playwright

统一接口：
    from crawlers.amazon_bsr import crawl_best_sellers, ProductDTO
"""
