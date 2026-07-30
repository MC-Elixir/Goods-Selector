from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from sqlalchemy import Engine, event, text
from sqlalchemy.engine import Connection

from db.migrations import MIGRATIONS


def install_sqlite_foreign_keys(engine: Engine) -> None:
    if engine.dialect.name != "sqlite" or getattr(engine, "_fk_listener", False):
        return

    def set_and_verify_foreign_keys(dbapi_connection) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA foreign_keys")
        enabled = cursor.fetchone()[0]
        cursor.close()
        if enabled != 1:
            raise RuntimeError("failed to enable SQLite foreign keys")

    @event.listens_for(engine, "connect")
    def set_foreign_keys_on_connect(dbapi_connection, _connection_record):
        set_and_verify_foreign_keys(dbapi_connection)

    @event.listens_for(engine, "checkout")
    def set_foreign_keys_on_checkout(dbapi_connection, _connection_record, _connection_proxy):
        set_and_verify_foreign_keys(dbapi_connection)

    setattr(engine, "_fk_listener", True)


def _validated_migrations() -> list[object]:
    versions: set[str] = set()
    ordered: list[object] = []
    for migration in MIGRATIONS:
        version = getattr(migration, "VERSION", None)
        if not isinstance(version, str) or not version.strip():
            raise ValueError("migrations must define a non-empty VERSION")
        if version in versions:
            raise ValueError(f"duplicate migration VERSION: {version}")
        versions.add(version)
        ordered.append(migration)
    return sorted(ordered, key=lambda item: item.VERSION)


def _run_sqlite_transaction(connection: Connection, operation: Callable[[], None]) -> None:
    connection.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        operation()
        connection.exec_driver_sql("COMMIT")
    except BaseException:
        connection.exec_driver_sql("ROLLBACK")
        raise


def _prepare_database(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version VARCHAR(120) PRIMARY KEY, "
                "applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            ))
        return

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        if connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
            raise RuntimeError("failed to enable SQLite foreign keys")
        if connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() != "ok":
            raise RuntimeError("database integrity_check failed")

        def create_version_table() -> None:
            connection.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version VARCHAR(120) PRIMARY KEY, "
                "applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )

        _run_sqlite_transaction(connection, create_version_table)


def _apply_sqlite_migration(engine: Engine, migration: object) -> bool:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        applied = False

        def upgrade() -> None:
            nonlocal applied
            exists = connection.execute(
                text("SELECT 1 FROM schema_migrations WHERE version=:version"),
                {"version": migration.VERSION},
            ).scalar_one_or_none()
            if exists is not None:
                return
            migration.upgrade(connection)
            connection.execute(
                text("INSERT INTO schema_migrations(version) VALUES (:version)"),
                {"version": migration.VERSION},
            )
            applied = True

        _run_sqlite_transaction(connection, upgrade)
        return applied


def _rollback_sqlite_migration(engine: Engine, migration: object) -> bool:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        rolled_back = False

        def downgrade() -> None:
            nonlocal rolled_back
            exists = connection.execute(
                text("SELECT 1 FROM schema_migrations WHERE version=:version"),
                {"version": migration.VERSION},
            ).scalar_one_or_none()
            if exists is None:
                return
            migration.down(connection)
            connection.execute(
                text("DELETE FROM schema_migrations WHERE version=:version"),
                {"version": migration.VERSION},
            )
            rolled_back = True

        _run_sqlite_transaction(connection, downgrade)
        return rolled_back


def run_migrations(engine: Engine) -> list[str]:
    migrations = _validated_migrations()
    install_sqlite_foreign_keys(engine)
    _prepare_database(engine)
    applied_now: list[str] = []
    for migration in migrations:
        if engine.dialect.name == "sqlite":
            if _apply_sqlite_migration(engine, migration):
                applied_now.append(migration.VERSION)
            continue
        with engine.begin() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM schema_migrations WHERE version=:version"),
                {"version": migration.VERSION},
            ).scalar_one_or_none()
            if exists is not None:
                continue
            migration.upgrade(connection)
            connection.execute(
                text("INSERT INTO schema_migrations(version) VALUES (:version)"),
                {"version": migration.VERSION},
            )
            applied_now.append(migration.VERSION)
    return applied_now


def rollback_migrations(engine: Engine, target_version: str) -> list[str]:
    """Roll back all migrations applied after *target_version*.

    Pass target_version="base" to roll back every migration.
    Returns the list of versions that were rolled back (descending order).
    """
    migrations = _validated_migrations()
    install_sqlite_foreign_keys(engine)
    _prepare_database(engine)

    if target_version != "base":
        known = {m.VERSION for m in migrations}
        if target_version not in known:
            raise ValueError(
                f"unknown target version: {target_version!r}. "
                f"Available: {', '.join(sorted(known))}"
            )

    # Determine which migrations to roll back (those after target, in reverse order)
    to_rollback: list[object] = []
    for migration in reversed(migrations):
        if target_version != "base" and migration.VERSION == target_version:
            break
        to_rollback.append(migration)

    rolled_back: list[str] = []
    for migration in to_rollback:
        if engine.dialect.name == "sqlite":
            if _rollback_sqlite_migration(engine, migration):
                rolled_back.append(migration.VERSION)
            continue
        with engine.begin() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM schema_migrations WHERE version=:version"),
                {"version": migration.VERSION},
            ).scalar_one_or_none()
            if exists is None:
                continue
            migration.down(connection)
            connection.execute(
                text("DELETE FROM schema_migrations WHERE version=:version"),
                {"version": migration.VERSION},
            )
            rolled_back.append(migration.VERSION)
    return rolled_back


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m db.migrate",
        description="Run or roll back database schema migrations.",
    )
    parser.add_argument(
        "--rollback",
        metavar="VERSION",
        default=None,
        help=(
            "Roll back all migrations applied after VERSION. "
            "Use 'base' to roll back everything."
        ),
    )
    args = parser.parse_args(argv)

    from db.session import engine

    if args.rollback is not None:
        rolled = rollback_migrations(engine, args.rollback)
        if rolled:
            print(f"Rolled back: {', '.join(rolled)}")
        else:
            print("Nothing to roll back.")
    else:
        applied = run_migrations(engine)
        if applied:
            print(f"Applied: {', '.join(applied)}")
        else:
            print("Database is up to date.")


if __name__ == "__main__":
    main(sys.argv[1:])
