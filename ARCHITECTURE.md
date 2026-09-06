# Architecture

The formal workflow is source-strict and linear:

```text
Amazon US category/keyword crawler
  -> SellerSprite reverse-keyword evidence per ASIN
  -> SellerSprite extension 1688 sourcing per ASIN
  -> real 1688 offer evidence (price/MOQ/spec/factory)
  -> deterministic profit, scoring and filtering
  -> one Excel workbook (+ background JSON)
```

Product discovery always calls the Amazon crawler. The public pipeline rejects
prebuilt `seed_products`. SellerSprite browser exports provide keyword/market
evidence, and its `1688找货` feature is the only formal supplier candidate source.
Open API, Scrapling, generic Playwright search, imports and mocks remain usable
for isolated diagnostics but are not fallback sources.

Missing extension configuration, authentication, permission, quota or captcha
becomes `HumanActionRequired`. Completed per-ASIN nodes are retained for resume.
Any positive `MJJL_MAX_PRODUCTS_PER_RUN` enables market collection for every
Amazon product in the formal run; it no longer truncates the batch. Zero is
reserved for explicit offline diagnostics.

The formal workbook contains `运行摘要`, `Amazon商品`, `卖家精灵市场数据`,
`Amazon×1688完整匹配`, and `未通过及待核验`. JSON is a machine sidecar;
Markdown exporters are compatibility utilities only.

Default Compose starts only `amazon-selector`. MCP uses the optional `assistant`
profile and Hermes is optional. Windows `start.ps1` starts/checks a loopback-only
Chrome endpoint, then verifies `host.docker.internal:9222` from inside the
container before opening `http://127.0.0.1:8765`; failure stops the service.
