"""一键建表：python -m db.init_db"""
from loguru import logger

from db.models import Base
from db.session import engine


def init_db() -> None:
    logger.info(f"Creating tables at {engine.url}")
    Base.metadata.create_all(engine)
    logger.info("Done.")


if __name__ == "__main__":
    init_db()
