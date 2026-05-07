"""Amazon Best Seller 数据采集层。

推荐数据源（按优先级）：
1. Keepa API — $19/月起，数据全且稳，pip install keepa
2. Rainforest API — 按调用计费
3. 自建爬虫 — 反爬严，不推荐

本模块对外暴露统一接口：
    crawl_best_sellers(category: str, limit: int) -> list[ProductDTO]
"""
