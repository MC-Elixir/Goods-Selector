"""Initialize legacy tables and apply additive migrations."""
from loguru import logger

from db.migrate import run_migrations
from db.models import (
    Base,
    MarketAnalysis,
    Product,
    ProfitSnapshot,
    RunEvent,
    RunLog,
    Score,
    Supplier,
)
from db.session import engine


def init_db() -> None:
    logger.info(f"Creating tables at {engine.url}")
    # Keep the original schema bootstrap for compatibility, but require all
    # additive execution/evidence structures to be created by versioned
    # migrations. This prevents ORM metadata from silently bypassing v0004.
    legacy_tables = [
        Product.__table__, Supplier.__table__, ProfitSnapshot.__table__,
        Score.__table__, MarketAnalysis.__table__, RunLog.__table__, RunEvent.__table__,
    ]
    Base.metadata.create_all(engine, tables=legacy_tables)
    applied = run_migrations(engine)
    logger.info(f"Database ready; migrations_applied={applied}")


if __name__ == "__main__":
    init_db()
