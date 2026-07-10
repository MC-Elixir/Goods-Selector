from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

import db.migrate as migrate
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


def test_failed_migration_rolls_back_objects_and_does_not_advance_version(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'rollback.db'}")

    def fail_after_ddl(connection):
        connection.exec_driver_sql("CREATE TABLE migration_partial (id INTEGER PRIMARY KEY)")
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(
        migrate,
        "MIGRATIONS",
        (SimpleNamespace(VERSION="9999_injected_failure", upgrade=fail_after_ddl),),
    )

    with pytest.raises(RuntimeError, match="injected migration failure"):
        run_migrations(engine)

    assert "migration_partial" not in inspect(engine).get_table_names()
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE version='9999_injected_failure'")
        ).scalar_one() == 0


def test_structured_migration_preserves_semicolons_in_triggers_strings_and_comments(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'semicolons.db'}")

    def upgrade(connection):
        connection.exec_driver_sql(
            "CREATE TABLE semicolon_events (id INTEGER PRIMARY KEY, note TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE semicolon_sources ("
            "id INTEGER PRIMARY KEY, value TEXT DEFAULT 'literal;value') /* comment; retained */"
        )
        connection.exec_driver_sql(
            """CREATE TRIGGER semicolon_trigger AFTER INSERT ON semicolon_sources
            BEGIN
                INSERT INTO semicolon_events(note) VALUES ('trigger;first');
                INSERT INTO semicolon_events(note) VALUES ('trigger;second');
            END"""
        )

    monkeypatch.setattr(
        migrate,
        "MIGRATIONS",
        (SimpleNamespace(VERSION="9998_semicolon_safety", upgrade=upgrade),),
    )

    assert run_migrations(engine) == ["9998_semicolon_safety"]
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO semicolon_sources(id) VALUES (1)"))
    with engine.connect() as conn:
        assert conn.execute(text("SELECT value FROM semicolon_sources")).scalar_one() == "literal;value"
        assert conn.execute(text("SELECT note FROM semicolon_events ORDER BY id")).scalars().all() == [
            "trigger;first",
            "trigger;second",
        ]


def test_foreign_keys_are_enabled_for_preheated_and_new_connections(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'foreign_keys.db'}")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 0

    def upgrade(connection):
        connection.exec_driver_sql("CREATE TABLE fk_parent (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE fk_child (id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL "
            "REFERENCES fk_parent(id))"
        )

    monkeypatch.setattr(
        migrate,
        "MIGRATIONS",
        (SimpleNamespace(VERSION="9997_foreign_keys", upgrade=upgrade),),
    )

    run_migrations(engine)
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        with pytest.raises(IntegrityError):
            conn.execute(text("INSERT INTO fk_child(id, parent_id) VALUES (1, 404)"))
        conn.rollback()

    engine.dispose()
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_missing_metrics_remain_null_and_explicit_zero_is_preserved(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'metric_semantics.db'}")
    run_migrations(engine)

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO query_attempts "
            "(run_ref, asin, query_id, query_type, query_text, reason, status, result_count, relevant_count) "
            "VALUES "
            "('run-null', 'ASINNULL', 'q-null', 'keyword', 'query', 'not run', 'not_started', NULL, NULL), "
            "('run-zero', 'ASINZERO', 'q-zero', 'keyword', 'query', 'ran', 'completed', 0, 0)"
        ))
        conn.execute(text(
            "INSERT INTO field_evidence "
            "(entity_type, entity_ref, field_name, status, source_provider) VALUES "
            "('product', 'ASINNULL', 'price', 'missing', 'amazon')"
        ))
        conn.execute(text(
            "INSERT INTO field_evidence "
            "(entity_type, entity_ref, field_name, status, source_provider, confidence) VALUES "
            "('product', 'ASINZERO', 'price', 'verified', 'amazon', 0)"
        ))
        conn.execute(text(
            "INSERT INTO match_evidence "
            "(run_ref, asin, offer_id, decision, evidence_json) VALUES "
            "('run-null', 'ASINNULL', 'offer-null', 'unknown', '{}')"
        ))
        conn.execute(text(
            "INSERT INTO match_evidence "
            "(run_ref, asin, offer_id, decision, overall_confidence, evidence_json) VALUES "
            "('run-zero', 'ASINZERO', 'offer-zero', 'reject', 0, '{}')"
        ))

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO query_attempts "
            "(run_ref, asin, query_id, query_type, query_text, reason, status) VALUES "
            "('run-invalid', 'ASINBAD', 'q-completed-null', 'keyword', 'query', 'bad', 'completed')"
        ))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO query_attempts "
            "(run_ref, asin, query_id, query_type, query_text, reason, status, result_count, relevant_count) "
            "VALUES ('run-invalid', 'ASINBAD', 'q-failed-zero', 'keyword', 'query', 'bad', 'failed', 0, 0)"
        ))

    with engine.connect() as conn:
        attempts = conn.execute(text(
            "SELECT query_id, result_count, relevant_count FROM query_attempts ORDER BY query_id"
        )).all()
        confidences = conn.execute(text(
            "SELECT entity_ref, confidence FROM field_evidence ORDER BY entity_ref"
        )).all()
        match_confidences = conn.execute(text(
            "SELECT offer_id, overall_confidence FROM match_evidence ORDER BY offer_id"
        )).all()
    assert attempts == [("q-null", None, None), ("q-zero", 0, 0)]
    assert confidences == [("ASINNULL", None), ("ASINZERO", 0.0)]
    assert match_confidences == [("offer-null", None), ("offer-zero", 0.0)]
