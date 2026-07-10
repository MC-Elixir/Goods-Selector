from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, event, text

MIGRATIONS = Path(__file__).with_name("migrations")


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    if engine.dialect.name != "sqlite" or getattr(engine, "_fk_listener", False):
        return

    @event.listens_for(engine, "connect")
    def set_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    setattr(engine, "_fk_listener", True)


def run_migrations(engine: Engine) -> list[str]:
    _enable_sqlite_foreign_keys(engine)
    applied_now: list[str] = []
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            if conn.execute(text("PRAGMA integrity_check")).scalar_one() != "ok":
                raise RuntimeError("database integrity_check failed")
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version VARCHAR(120) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
        applied = set(conn.execute(text("SELECT version FROM schema_migrations")).scalars())
        for path in sorted(MIGRATIONS.glob("*.sql")):
            version = path.stem
            if version in applied:
                continue
            raw = path.read_text(encoding="utf-8")
            for statement in (part.strip() for part in raw.split(";")):
                if statement:
                    conn.exec_driver_sql(statement)
            conn.execute(text("INSERT INTO schema_migrations(version) VALUES (:version)"), {"version": version})
            applied_now.append(version)
    return applied_now
