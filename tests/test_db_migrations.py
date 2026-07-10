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
    assert run_migrations(engine) == ["0001_evidence_foundation", "0002_repair_evidence_semantics"]
    assert run_migrations(engine) == []
    names = set(inspect(engine).get_table_names())
    assert {"field_evidence", "query_attempts", "match_evidence", "sourcing_recommendations"} <= names
    evidence_index = next(
        index
        for index in inspect(engine).get_indexes("field_evidence")
        if index["name"] == "ix_field_evidence_entity"
    )
    assert evidence_index["column_names"] == ["entity_type", "entity_ref"]
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
    preheated = [engine.connect() for _ in range(3)]
    for connection in preheated:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 0
        connection.close()

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
    checked_out = [engine.connect() for _ in range(3)]
    try:
        assert [
            connection.execute(text("PRAGMA foreign_keys")).scalar_one()
            for connection in checked_out
        ] == [1, 1, 1]
        with pytest.raises(IntegrityError):
            checked_out[0].execute(text("INSERT INTO fk_child(id, parent_id) VALUES (1, 404)"))
        checked_out[0].rollback()
    finally:
        for connection in checked_out:
            connection.close()

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


def test_legacy_0001_database_is_repaired_without_losing_history(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy_0001.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE schema_migrations ("
            "version VARCHAR(120) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        connection.execute(text(
            "INSERT INTO schema_migrations(version) VALUES ('0001_evidence_foundation')"
        ))
        connection.exec_driver_sql(
            """CREATE TABLE field_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type VARCHAR(40) NOT NULL,
                entity_ref VARCHAR(120) NOT NULL,
                field_name VARCHAR(120) NOT NULL,
                value_json TEXT,
                status VARCHAR(20) NOT NULL,
                source_provider VARCHAR(80) NOT NULL,
                source_type VARCHAR(80),
                source_ref TEXT,
                observed_at TIMESTAMP,
                expires_at TIMESTAMP,
                confidence REAL NOT NULL DEFAULT 0,
                extraction_method VARCHAR(80),
                schema_version VARCHAR(20) NOT NULL DEFAULT '1.0',
                conflict_refs_json TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK (status IN ('verified','extracted','inferred','stale','missing','mock','conflicting')),
                CHECK (confidence >= 0 AND confidence <= 1)
            )"""
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_field_evidence_entity ON field_evidence(entity_type, entity_ref)"
        )
        connection.exec_driver_sql(
            """CREATE TABLE query_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_ref VARCHAR(80) NOT NULL,
                asin VARCHAR(20) NOT NULL,
                query_id VARCHAR(80) NOT NULL,
                query_type VARCHAR(40) NOT NULL,
                query_text VARCHAR(120) NOT NULL,
                reason TEXT NOT NULL,
                excluded_brand_tokens_json TEXT NOT NULL DEFAULT '[]',
                backend VARCHAR(60),
                result_count INTEGER NOT NULL DEFAULT 0,
                relevant_count INTEGER NOT NULL DEFAULT 0,
                retry_of VARCHAR(80),
                status VARCHAR(20) NOT NULL,
                artifact_ref TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(run_ref, query_id)
            )"""
        )
        connection.exec_driver_sql(
            """CREATE TABLE match_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_ref VARCHAR(80) NOT NULL,
                asin VARCHAR(20) NOT NULL,
                offer_id VARCHAR(40) NOT NULL,
                decision VARCHAR(20) NOT NULL,
                overall_confidence REAL NOT NULL,
                evidence_json TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(run_ref, asin, offer_id)
            )"""
        )
        connection.exec_driver_sql(
            """CREATE TABLE sourcing_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_ref VARCHAR(80) NOT NULL,
                asin VARCHAR(20) NOT NULL,
                offer_id VARCHAR(40),
                status VARCHAR(30) NOT NULL,
                evidence_json TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(run_ref, asin, offer_id)
            )"""
        )
        connection.execute(text(
            "INSERT INTO field_evidence "
            "(id, entity_type, entity_ref, field_name, status, source_provider, confidence) VALUES "
            "(7, 'product', 'MISSING', 'price', 'missing', 'amazon', 0), "
            "(8, 'product', 'UNKNOWNZERO', 'price', 'verified', 'amazon', 0), "
            "(9, 'product', 'KNOWN', 'price', 'verified', 'amazon', 0.75)"
        ))
        connection.execute(text(
            "INSERT INTO query_attempts "
            "(id, run_ref, asin, query_id, query_type, query_text, reason, result_count, relevant_count, status) "
            "VALUES "
            "(11, 'legacy', 'A1', 'completed', 'keyword', 'q', 'done', 0, 0, 'completed'), "
            "(12, 'legacy', 'A2', 'failed', 'keyword', 'q', 'failed', 0, 0, 'failed'), "
            "(13, 'legacy', 'A3', 'partial', 'keyword', 'q', 'partial', 3, 1, 'partial'), "
            "(14, 'legacy', 'A4', 'not-started', 'keyword', 'q', 'waiting', 0, 0, 'not_started'), "
            "(15, 'legacy', 'A5', 'completed-nonzero', 'keyword', 'q', 'done', 3, 1, 'completed'), "
            "(16, 'legacy', 'A6', 'unknown-status', 'keyword', 'q', 'unknown', -2, -1, 'mystery'), "
            "(99, 'legacy', 'A99', 'deleted-high-water', 'keyword', 'q', 'deleted', 1, 1, 'completed')"
        ))
        connection.execute(text(
            "INSERT INTO match_evidence "
            "(id, run_ref, asin, offer_id, decision, overall_confidence, evidence_json) VALUES "
            "(21, 'legacy', 'A1', 'offer-zero', 'unknown', 0, '{}'), "
            "(22, 'legacy', 'A2', 'offer-known', 'accept', 0.8, '{}'), "
            "(23, 'legacy', 'A3', 'offer-invalid', 'reject', 1.5, '{}'), "
            "(99, 'legacy', 'A99', 'deleted-high-water', 'accept', 0.6, '{}')"
        ))
        connection.execute(text(
            "INSERT INTO sourcing_recommendations "
            "(id, run_ref, asin, offer_id, status, evidence_json) VALUES "
            "(31, 'legacy', 'A1', 'offer-zero', 'review', '{}')"
        ))
        connection.execute(text("INSERT INTO field_evidence "
            "(id, entity_type, entity_ref, field_name, status, source_provider, confidence) VALUES "
            "(99, 'product', 'DELETED-HIGH-WATER', 'price', 'verified', 'amazon', 0.5)"))
        connection.execute(text("DELETE FROM field_evidence WHERE id=99"))
        connection.execute(text("DELETE FROM query_attempts WHERE id=99"))
        connection.execute(text("DELETE FROM match_evidence WHERE id=99"))

    assert run_migrations(engine) == ["0002_repair_evidence_semantics"]
    assert run_migrations(engine) == []

    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT id, entity_ref, confidence FROM field_evidence ORDER BY id"
        )).all() == [
            (7, "MISSING", None),
            (8, "UNKNOWNZERO", None),
            (9, "KNOWN", 0.75),
        ]
        assert connection.execute(text(
            "SELECT id, query_id, status, result_count, relevant_count FROM query_attempts ORDER BY id"
        )).all() == [
            (11, "completed", "partial", None, None),
            (12, "failed", "failed", None, None),
            (13, "partial", "partial", None, None),
            (14, "not-started", "not_started", None, None),
            (15, "completed-nonzero", "completed", 3, 1),
            (16, "unknown-status", "partial", None, None),
        ]
        assert connection.execute(text(
            "SELECT id, offer_id, overall_confidence FROM match_evidence ORDER BY id"
        )).all() == [
            (21, "offer-zero", 0.0),
            (22, "offer-known", 0.8),
            (23, "offer-invalid", None),
        ]
        assert connection.execute(text(
            "SELECT id, status FROM sourcing_recommendations"
        )).one() == (31, "review")
        assert connection.execute(text(
            "SELECT source_table, source_id, field_name, original_value_json, reason "
            "FROM legacy_evidence_audit ORDER BY source_table, source_id, field_name"
        )).all() == [
            ("field_evidence", 7, "confidence", "0.0", "legacy_default_or_explicit_zero_unknown"),
            ("field_evidence", 8, "confidence", "0.0", "legacy_default_or_explicit_zero_unknown"),
            ("match_evidence", 23, "overall_confidence", "1.5", "legacy_confidence_out_of_range"),
            ("query_attempts", 11, "relevant_count", "0", "legacy_completed_zero_counts_unknown"),
            ("query_attempts", 11, "result_count", "0", "legacy_completed_zero_counts_unknown"),
            ("query_attempts", 11, "status", '"completed"', "legacy_completed_zero_counts_unknown"),
            ("query_attempts", 12, "relevant_count", "0", "legacy_status_requires_null_metrics"),
            ("query_attempts", 12, "result_count", "0", "legacy_status_requires_null_metrics"),
            ("query_attempts", 13, "relevant_count", "1", "legacy_status_requires_null_metrics"),
            ("query_attempts", 13, "result_count", "3", "legacy_status_requires_null_metrics"),
            ("query_attempts", 14, "relevant_count", "0", "legacy_status_requires_null_metrics"),
            ("query_attempts", 14, "result_count", "0", "legacy_status_requires_null_metrics"),
            ("query_attempts", 16, "relevant_count", "-1", "legacy_negative_count_invalid"),
            ("query_attempts", 16, "result_count", "-2", "legacy_negative_count_invalid"),
            ("query_attempts", 16, "status", '"mystery"', "legacy_status_unknown"),
        ]
        connection.execute(text(
            "INSERT INTO field_evidence (entity_type, entity_ref, field_name, status, source_provider) "
            "VALUES ('product', 'AFTER-UPGRADE', 'price', 'missing', 'amazon')"
        ))
        connection.execute(text(
            "INSERT INTO query_attempts "
            "(run_ref, asin, query_id, query_type, query_text, reason, status, result_count, relevant_count) "
            "VALUES ('new', 'NEW', 'after-upgrade', 'keyword', 'q', 'done', 'completed', 1, 1)"
        ))
        connection.execute(text(
            "INSERT INTO match_evidence (run_ref, asin, offer_id, decision, evidence_json) "
            "VALUES ('new', 'NEW', 'after-upgrade', 'accept', '{}')"
        ))
        assert connection.execute(text("SELECT id FROM field_evidence WHERE entity_ref='AFTER-UPGRADE'")).scalar_one() == 100
        assert connection.execute(text("SELECT id FROM query_attempts WHERE query_id='after-upgrade'")).scalar_one() == 100
        assert connection.execute(text("SELECT id FROM match_evidence WHERE offer_id='after-upgrade'")).scalar_one() == 100
        assert connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"

    evidence_index = next(
        index
        for index in inspect(engine).get_indexes("field_evidence")
        if index["name"] == "ix_field_evidence_entity"
    )
    assert evidence_index["column_names"] == ["entity_type", "entity_ref"]
    assert {
        tuple(constraint["column_names"])
        for constraint in inspect(engine).get_unique_constraints("query_attempts")
    } == {
        ("run_ref", "query_id")
    }


@pytest.mark.parametrize(
    ("registry", "message"),
    [
        ((SimpleNamespace(VERSION="", upgrade=lambda _connection: None),), "non-empty VERSION"),
        (
            (
                SimpleNamespace(VERSION="duplicate", upgrade=lambda _connection: None),
                SimpleNamespace(VERSION="duplicate", upgrade=lambda _connection: None),
            ),
            "duplicate migration VERSION",
        ),
    ],
)
def test_migration_registry_rejects_invalid_versions(tmp_path, monkeypatch, registry, message):
    engine = create_engine(f"sqlite:///{tmp_path / 'invalid_registry.db'}")
    monkeypatch.setattr(migrate, "MIGRATIONS", registry)

    with pytest.raises(ValueError, match=message):
        run_migrations(engine)

    assert inspect(engine).get_table_names() == []
