-- ============================================================
-- Amazon Selector - 数据库 DDL
-- 兼容 PostgreSQL & SQLite
-- 字段命名 snake_case，时间一律 UTC
-- ============================================================

-- ------------------------------------------------------------
-- 1. products  Amazon 产品主表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    id                    INTEGER       PRIMARY KEY AUTOINCREMENT,
    asin                  VARCHAR(20)   NOT NULL,
    marketplace           VARCHAR(8)    NOT NULL DEFAULT 'US',

    category              VARCHAR(120),
    subcategory           VARCHAR(120),

    title                 TEXT          NOT NULL,
    brand                 VARCHAR(120),

    price                 REAL,
    bsr_rank              INTEGER,
    rating                REAL,
    review_count          INTEGER,
    review_velocity_30d   INTEGER,

    weight_kg             REAL,
    length_cm             REAL,
    width_cm              REAL,
    height_cm             REAL,

    main_image_url        TEXT,
    listing_url           TEXT,
    raw_data              TEXT,           -- JSON

    first_seen_at         TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_updated_at       TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_product_asin_marketplace UNIQUE (asin, marketplace)
);

CREATE INDEX IF NOT EXISTS ix_product_asin       ON products(asin);
CREATE INDEX IF NOT EXISTS ix_product_category   ON products(category);
CREATE INDEX IF NOT EXISTS ix_product_brand      ON products(brand);
CREATE INDEX IF NOT EXISTS ix_product_bsr_rank   ON products(bsr_rank);
CREATE INDEX IF NOT EXISTS ix_product_cat_bsr    ON products(category, bsr_rank);


-- ------------------------------------------------------------
-- 2. suppliers  1688 货源（一对多）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS suppliers (
    id                    INTEGER       PRIMARY KEY AUTOINCREMENT,
    product_id            INTEGER       NOT NULL,

    alibaba_offer_id      VARCHAR(40)   NOT NULL,
    supplier_name         VARCHAR(200),
    supplier_url          TEXT,
    offer_url             TEXT,
    offer_image_url       TEXT,

    image_similarity      REAL,
    text_similarity       REAL,

    moq                   INTEGER,
    price_tiers           TEXT,           -- JSON: [{qty,price}]
    base_price_cny        REAL,

    monthly_sales         INTEGER,
    repeat_buyer_rate     REAL,
    is_factory            BOOLEAN,

    matched_at            TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_supplier_product
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    CONSTRAINT uq_supplier_product_offer UNIQUE (product_id, alibaba_offer_id)
);

CREATE INDEX IF NOT EXISTS ix_supplier_product_id     ON suppliers(product_id);
CREATE INDEX IF NOT EXISTS ix_supplier_alibaba_offer  ON suppliers(alibaba_offer_id);
CREATE INDEX IF NOT EXISTS ix_supplier_image_sim      ON suppliers(image_similarity);


-- ------------------------------------------------------------
-- 3. profit_snapshots  利润快照
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS profit_snapshots (
    id                    INTEGER       PRIMARY KEY AUTOINCREMENT,
    product_id            INTEGER       NOT NULL,
    supplier_id           INTEGER       NOT NULL,

    selling_price         REAL          NOT NULL,
    batch_qty             INTEGER       NOT NULL DEFAULT 200,

    purchase_cost         REAL          NOT NULL DEFAULT 0,
    shipping_cost         REAL          NOT NULL DEFAULT 0,
    fba_fee               REAL          NOT NULL DEFAULT 0,
    commission            REAL          NOT NULL DEFAULT 0,
    ad_cost               REAL          NOT NULL DEFAULT 0,
    return_loss           REAL          NOT NULL DEFAULT 0,
    exchange_loss         REAL          NOT NULL DEFAULT 0,
    other_costs           REAL          NOT NULL DEFAULT 0,

    total_cost            REAL          NOT NULL DEFAULT 0,
    net_profit            REAL          NOT NULL DEFAULT 0,
    profit_margin         REAL          NOT NULL DEFAULT 0,

    params_version        VARCHAR(40),
    params_snapshot       TEXT,           -- JSON

    snapshot_at           TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_profit_product  FOREIGN KEY (product_id)  REFERENCES products(id)  ON DELETE CASCADE,
    CONSTRAINT fk_profit_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_profit_product_id   ON profit_snapshots(product_id);
CREATE INDEX IF NOT EXISTS ix_profit_snapshot_at  ON profit_snapshots(snapshot_at);


-- ------------------------------------------------------------
-- 4. scores  多维度评分
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scores (
    id                    INTEGER       PRIMARY KEY AUTOINCREMENT,
    product_id            INTEGER       NOT NULL,

    profit_score          REAL          NOT NULL DEFAULT 0,
    demand_score          REAL          NOT NULL DEFAULT 0,
    competition_score     REAL          NOT NULL DEFAULT 0,
    supply_score          REAL          NOT NULL DEFAULT 0,
    logistics_score       REAL          NOT NULL DEFAULT 0,
    risk_score            REAL          NOT NULL DEFAULT 0,
    total_score           REAL          NOT NULL DEFAULT 0,

    passed_hard_filter    BOOLEAN       NOT NULL DEFAULT 0,
    rejection_reasons     TEXT,           -- JSON

    weights_version       VARCHAR(40),
    weights_snapshot      TEXT,           -- JSON

    scored_at             TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_score_product
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_score_product_id   ON scores(product_id);
CREATE INDEX IF NOT EXISTS ix_score_total        ON scores(total_score);
CREATE INDEX IF NOT EXISTS ix_score_passed       ON scores(passed_hard_filter);
CREATE INDEX IF NOT EXISTS ix_score_scored_at    ON scores(scored_at);


-- ------------------------------------------------------------
-- 5. market_analyses  卖家精灵市场数据
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_analyses (
    id                          INTEGER     PRIMARY KEY AUTOINCREMENT,
    product_id                  INTEGER     NOT NULL,

    main_keyword                VARCHAR(200),
    search_volume_monthly       INTEGER,
    keyword_difficulty          REAL,

    competing_listings          INTEGER,
    top10_revenue_share         REAL,
    avg_review_count_top10      INTEGER,
    avg_price_top10             REAL,

    opportunity_score           REAL,
    seasonality                 TEXT,       -- JSON
    raw_data                    TEXT,       -- JSON

    analyzed_at                 TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_market_product
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_market_product_id   ON market_analyses(product_id);


-- ------------------------------------------------------------
-- 6. run_logs  流水线执行日志
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS run_logs (
    id                          INTEGER     PRIMARY KEY AUTOINCREMENT,

    pipeline_version            VARCHAR(40),
    category                    VARCHAR(120),
    marketplace                 VARCHAR(8),

    products_crawled            INTEGER     NOT NULL DEFAULT 0,
    suppliers_matched           INTEGER     NOT NULL DEFAULT 0,
    profits_calculated          INTEGER     NOT NULL DEFAULT 0,
    candidates_after_filter     INTEGER     NOT NULL DEFAULT 0,
    api_calls                   TEXT,       -- JSON

    started_at                  TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at                 TIMESTAMP,
    status                      VARCHAR(20) NOT NULL DEFAULT 'running',
    error_message               TEXT
);


-- ------------------------------------------------------------
-- 视图：当前每个 product 的最新评分（方便业务查询）
-- ------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_latest_scores AS
SELECT
    p.id            AS product_id,
    p.asin,
    p.title,
    p.category,
    p.price,
    s.total_score,
    s.passed_hard_filter,
    s.scored_at
FROM products p
JOIN scores s ON s.id = (
    SELECT id FROM scores
    WHERE product_id = p.id
    ORDER BY scored_at DESC
    LIMIT 1
);
