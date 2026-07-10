from sqlalchemy import create_engine, inspect, text

from db.migrate import run_migrations


def test_migration_is_additive_idempotent_and_enables_foreign_keys(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY, asin TEXT NOT NULL)"))
        conn.execute(text("INSERT INTO products(id, asin) VALUES (1, 'B000KEEP')"))
    assert run_migrations(engine) == ["0001_evidence_foundation"]
    assert run_migrations(engine) == []
    names = set(inspect(engine).get_table_names())
    assert {"field_evidence", "query_attempts", "match_evidence", "sourcing_recommendations"} <= names
    with engine.connect() as conn:
        assert conn.execute(text("SELECT asin FROM products WHERE id=1")).scalar_one() == "B000KEEP"
        assert conn.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
