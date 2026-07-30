"""Add seller-research shortlist tables for the market-research workflow."""

from sqlalchemy.engine import Connection

VERSION = "0005_seller_research"


def upgrade(connection: Connection) -> None:
    """Create the seller-research run manifest and its per-seller item rows."""

    connection.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS seller_research_runs (
            id VARCHAR(36) PRIMARY KEY,
            niche_label VARCHAR(200) NOT NULL,
            keyword VARCHAR(200),
            marketplace VARCHAR(8) NOT NULL DEFAULT 'US',
            source_provider VARCHAR(80) NOT NULL,
            source_type VARCHAR(80) NOT NULL,
            source_file TEXT NOT NULL,
            file_sha256 VARCHAR(64) NOT NULL,
            observed_at TIMESTAMP NOT NULL,
            imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            row_count INTEGER NOT NULL,
            eligible_count INTEGER NOT NULL DEFAULT 0,
            excluded_count INTEGER NOT NULL DEFAULT 0,
            ruleset_version VARCHAR(40) NOT NULL,
            quality_summary_json TEXT NOT NULL,
            export_file TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'imported'
        )"""
    )
    connection.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS seller_research_items (
            id VARCHAR(36) PRIMARY KEY,
            run_id VARCHAR(36) NOT NULL REFERENCES seller_research_runs(id) ON DELETE CASCADE,
            rank_index INTEGER NOT NULL DEFAULT 0,
            seller VARCHAR(300) NOT NULL,
            representative_asin VARCHAR(20),
            representative_title TEXT,
            brand VARCHAR(200),
            price REAL,
            rating REAL,
            review_count INTEGER,
            launch_date VARCHAR(40),
            launch_months REAL,
            monthly_sales INTEGER,
            monthly_revenue REAL,
            seller_product_count INTEGER,
            product_count_source VARCHAR(20),
            fit_category VARCHAR(60) NOT NULL,
            fit_category_label VARCHAR(60),
            fit_score REAL NOT NULL DEFAULT 0,
            excluded INTEGER NOT NULL DEFAULT 0,
            fit_factors_json TEXT NOT NULL DEFAULT '{}',
            fit_reasons_json TEXT NOT NULL DEFAULT '[]',
            exclusion_reasons_json TEXT NOT NULL DEFAULT '[]',
            ai_reason TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_seller_research_runs_niche "
        "ON seller_research_runs(niche_label, imported_at)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_seller_research_items_run "
        "ON seller_research_items(run_id, rank_index)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_seller_research_items_category "
        "ON seller_research_items(fit_category, fit_score)"
    )


def down(connection: Connection) -> None:
    """Drop seller-research tables and indexes."""

    connection.exec_driver_sql("DROP INDEX IF EXISTS ix_seller_research_items_category")
    connection.exec_driver_sql("DROP INDEX IF EXISTS ix_seller_research_items_run")
    connection.exec_driver_sql("DROP INDEX IF EXISTS ix_seller_research_runs_niche")
    connection.exec_driver_sql("DROP TABLE IF EXISTS seller_research_items")
    connection.exec_driver_sql("DROP TABLE IF EXISTS seller_research_runs")
