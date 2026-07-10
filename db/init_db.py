"""Initialize legacy tables and apply additive migrations."""
from loguru import logger

from db.migrate import run_migrations
from db.models import Base
from db.session import engine


def init_db() -> None:
    logger.info(f"Creating tables at {engine.url}")
    Base.metadata.create_all(engine)
    applied = run_migrations(engine)
    logger.info(f"Database ready; migrations_applied={applied}")


if __name__ == "__main__":
    init_db()
