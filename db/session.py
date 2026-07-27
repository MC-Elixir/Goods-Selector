"""数据库 session 管理。"""
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import settings
from db.migrate import install_sqlite_foreign_keys

engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    # SQLite 多线程支持
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)
install_sqlite_foreign_keys(engine)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务上下文：with session_scope() as s: ..."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
