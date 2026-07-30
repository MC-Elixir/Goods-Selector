"""Repair evidence tables created by the original 0001 migration."""

from sqlalchemy.engine import Connection

VERSION = "0002_repair_evidence_semantics"


def _create_legacy_audit_table(connection: Connection) -> None:
    """Retain values that cannot be represented by the corrected invariants."""
    connection.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS legacy_evidence_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_version VARCHAR(120) NOT NULL,
            source_table VARCHAR(80) NOT NULL,
            source_id INTEGER NOT NULL,
            field_name VARCHAR(80) NOT NULL,
            original_value_json TEXT NOT NULL,
            reason VARCHAR(80) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(migration_version, source_table, source_id, field_name)
        )"""
    )


def _column_requires_rebuild(connection: Connection, table: str, column: str) -> bool:
    columns = connection.exec_driver_sql(f'PRAGMA table_info("{table}")').mappings()
    metadata = next(row for row in columns if row["name"] == column)
    return bool(metadata["notnull"]) or metadata["dflt_value"] is not None


def _assert_row_count_preserved(connection: Connection, old_table: str, new_table: str) -> None:
    old_count = connection.exec_driver_sql(f'SELECT COUNT(*) FROM "{old_table}"').scalar_one()
    new_count = connection.exec_driver_sql(f'SELECT COUNT(*) FROM "{new_table}"').scalar_one()
    if old_count != new_count:
        raise RuntimeError(f"row count mismatch while rebuilding {old_table}")


def _sequence_high_water(connection: Connection, table: str) -> int:
    if connection.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
    ).scalar_one_or_none() is None:
        return 0
    return connection.exec_driver_sql(
        "SELECT COALESCE((SELECT seq FROM sqlite_sequence WHERE name=?), 0)", (table,)
    ).scalar_one()


def _restore_sequence_high_water(connection: Connection, table: str, old_sequence: int) -> None:
    current_max = connection.exec_driver_sql(
        f'SELECT COALESCE(MAX(id), 0) FROM "{table}"'
    ).scalar_one()
    target = max(old_sequence, current_max)
    updated = connection.exec_driver_sql(
        "UPDATE sqlite_sequence SET seq=? WHERE name=?", (target, table)
    ).rowcount
    if updated == 0:
        connection.exec_driver_sql(
            "INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)", (table, target)
        )


def _repair_field_evidence(connection: Connection) -> None:
    if not _column_requires_rebuild(connection, "field_evidence", "confidence"):
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_field_evidence_entity "
            "ON field_evidence(entity_type, entity_ref)"
        )
        return
    old_sequence = _sequence_high_water(connection, "field_evidence")
    connection.exec_driver_sql("DROP TABLE IF EXISTS field_evidence__v0002")
    connection.exec_driver_sql(
        """CREATE TABLE field_evidence__v0002 (
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
            confidence REAL,
            extraction_method VARCHAR(80),
            schema_version VARCHAR(20) NOT NULL DEFAULT '1.0',
            conflict_refs_json TEXT NOT NULL DEFAULT '[]',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (status IN ('verified','extracted','inferred','stale','missing','mock','conflicting')),
            CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
        )"""
    )
    connection.exec_driver_sql(
        """INSERT INTO legacy_evidence_audit (
            migration_version, source_table, source_id, field_name,
            original_value_json, reason
        )
        SELECT
            '0002_repair_evidence_semantics', 'field_evidence', id, 'confidence',
            CAST(confidence AS TEXT), 'legacy_default_or_explicit_zero_unknown'
        FROM field_evidence
        WHERE confidence = 0"""
    )
    connection.exec_driver_sql(
        """INSERT INTO field_evidence__v0002 (
            id, entity_type, entity_ref, field_name, value_json, status,
            source_provider, source_type, source_ref, observed_at, expires_at,
            confidence, extraction_method, schema_version, conflict_refs_json, created_at
        )
        SELECT
            id, entity_type, entity_ref, field_name, value_json, status,
            source_provider, source_type, source_ref, observed_at, expires_at,
            CASE WHEN confidence = 0 THEN NULL ELSE confidence END,
            extraction_method, schema_version, conflict_refs_json, created_at
        FROM field_evidence"""
    )
    _assert_row_count_preserved(connection, "field_evidence", "field_evidence__v0002")
    connection.exec_driver_sql("DROP TABLE field_evidence")
    connection.exec_driver_sql("ALTER TABLE field_evidence__v0002 RENAME TO field_evidence")
    _restore_sequence_high_water(connection, "field_evidence", old_sequence)
    connection.exec_driver_sql(
        "CREATE INDEX ix_field_evidence_entity ON field_evidence(entity_type, entity_ref)"
    )


def _repair_query_attempts(connection: Connection) -> None:
    needs_rebuild = any(
        _column_requires_rebuild(connection, "query_attempts", column)
        for column in ("result_count", "relevant_count")
    )
    if not needs_rebuild:
        return
    old_sequence = _sequence_high_water(connection, "query_attempts")
    connection.exec_driver_sql("DROP TABLE IF EXISTS query_attempts__v0002")
    connection.exec_driver_sql(
        """CREATE TABLE query_attempts__v0002 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ref VARCHAR(80) NOT NULL,
            asin VARCHAR(20) NOT NULL,
            query_id VARCHAR(80) NOT NULL,
            query_type VARCHAR(40) NOT NULL,
            query_text VARCHAR(120) NOT NULL,
            reason TEXT NOT NULL,
            excluded_brand_tokens_json TEXT NOT NULL DEFAULT '[]',
            backend VARCHAR(60),
            result_count INTEGER,
            relevant_count INTEGER,
            retry_of VARCHAR(80),
            status VARCHAR(20) NOT NULL,
            artifact_ref TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(run_ref, query_id),
            CHECK (status IN ('not_started','completed','failed','partial')),
            CHECK (result_count IS NULL OR result_count >= 0),
            CHECK (relevant_count IS NULL OR relevant_count >= 0),
            CHECK (
                (status = 'completed' AND result_count IS NOT NULL AND relevant_count IS NOT NULL)
                OR
                (status IN ('not_started','failed','partial')
                    AND result_count IS NULL AND relevant_count IS NULL)
            )
        )"""
    )
    connection.exec_driver_sql(
        """INSERT INTO legacy_evidence_audit (
            migration_version, source_table, source_id, field_name,
            original_value_json, reason
        )
        SELECT
            '0002_repair_evidence_semantics', 'query_attempts', id, 'status',
            json_quote(status),
            CASE
                WHEN status NOT IN ('not_started', 'completed', 'failed', 'partial')
                    THEN 'legacy_status_unknown'
                WHEN result_count < 0 OR relevant_count < 0
                    THEN 'legacy_completed_negative_counts_invalid'
                ELSE 'legacy_completed_zero_counts_unknown'
            END
        FROM query_attempts
        WHERE status NOT IN ('not_started', 'completed', 'failed', 'partial')
           OR (status = 'completed' AND (result_count <= 0 OR relevant_count <= 0))"""
    )
    for field_name in ("result_count", "relevant_count"):
        connection.exec_driver_sql(
            f"""INSERT INTO legacy_evidence_audit (
                migration_version, source_table, source_id, field_name,
                original_value_json, reason
            )
            SELECT
                '0002_repair_evidence_semantics', 'query_attempts', id, '{field_name}',
                CAST({field_name} AS TEXT),
                CASE
                    WHEN {field_name} < 0 THEN 'legacy_negative_count_invalid'
                    WHEN status NOT IN ('not_started', 'completed', 'failed', 'partial')
                        THEN 'legacy_status_unknown'
                    WHEN status = 'completed' AND (result_count <= 0 OR relevant_count <= 0)
                        THEN 'legacy_completed_zero_counts_unknown'
                    ELSE 'legacy_status_requires_null_metrics'
                END
            FROM query_attempts
            WHERE NOT (
                status = 'completed' AND result_count > 0 AND relevant_count > 0
            )"""
        )
    connection.exec_driver_sql(
        """INSERT INTO query_attempts__v0002 (
            id, run_ref, asin, query_id, query_type, query_text, reason,
            excluded_brand_tokens_json, backend, result_count, relevant_count,
            retry_of, status, artifact_ref, created_at
        )
        SELECT
            id, run_ref, asin, query_id, query_type, query_text, reason,
            excluded_brand_tokens_json, backend,
            CASE
                WHEN status = 'completed' AND result_count > 0 AND relevant_count > 0
                    THEN result_count
                ELSE NULL
            END,
            CASE
                WHEN status = 'completed' AND result_count > 0 AND relevant_count > 0
                    THEN relevant_count
                ELSE NULL
            END,
            retry_of,
            CASE
                WHEN status = 'completed' AND result_count > 0 AND relevant_count > 0
                    THEN 'completed'
                WHEN status IN ('not_started', 'failed', 'partial') THEN status
                ELSE 'partial'
            END,
            artifact_ref, created_at
        FROM query_attempts"""
    )
    _assert_row_count_preserved(connection, "query_attempts", "query_attempts__v0002")
    connection.exec_driver_sql("DROP TABLE query_attempts")
    connection.exec_driver_sql("ALTER TABLE query_attempts__v0002 RENAME TO query_attempts")
    _restore_sequence_high_water(connection, "query_attempts", old_sequence)


def _repair_match_evidence(connection: Connection) -> None:
    if not _column_requires_rebuild(connection, "match_evidence", "overall_confidence"):
        return
    old_sequence = _sequence_high_water(connection, "match_evidence")
    connection.exec_driver_sql("DROP TABLE IF EXISTS match_evidence__v0002")
    connection.exec_driver_sql(
        """CREATE TABLE match_evidence__v0002 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ref VARCHAR(80) NOT NULL,
            asin VARCHAR(20) NOT NULL,
            offer_id VARCHAR(40) NOT NULL,
            decision VARCHAR(20) NOT NULL,
            overall_confidence REAL,
            evidence_json TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(run_ref, asin, offer_id),
            CHECK (overall_confidence IS NULL
                OR (overall_confidence >= 0 AND overall_confidence <= 1))
        )"""
    )
    connection.exec_driver_sql(
        """INSERT INTO legacy_evidence_audit (
            migration_version, source_table, source_id, field_name,
            original_value_json, reason
        )
        SELECT
            '0002_repair_evidence_semantics', 'match_evidence', id, 'overall_confidence',
            CAST(overall_confidence AS TEXT), 'legacy_confidence_out_of_range'
        FROM match_evidence
        WHERE overall_confidence < 0 OR overall_confidence > 1"""
    )
    connection.exec_driver_sql(
        """INSERT INTO match_evidence__v0002 (
            id, run_ref, asin, offer_id, decision, overall_confidence,
            evidence_json, created_at
        )
        SELECT
            id, run_ref, asin, offer_id, decision,
            CASE
                WHEN overall_confidence >= 0 AND overall_confidence <= 1
                    THEN overall_confidence
                ELSE NULL
            END,
            evidence_json, created_at
        FROM match_evidence"""
    )
    _assert_row_count_preserved(connection, "match_evidence", "match_evidence__v0002")
    connection.exec_driver_sql("DROP TABLE match_evidence")
    connection.exec_driver_sql("ALTER TABLE match_evidence__v0002 RENAME TO match_evidence")
    _restore_sequence_high_water(connection, "match_evidence", old_sequence)


def upgrade(connection: Connection) -> None:
    _create_legacy_audit_table(connection)
    _repair_field_evidence(connection)
    _repair_query_attempts(connection)
    _repair_match_evidence(connection)


def down(connection: Connection) -> None:
    """Drop the legacy audit table created by this migration.

    Note: data transformations (confidence/status repairs) cannot be reversed.
    """

    connection.exec_driver_sql("DROP TABLE IF EXISTS legacy_evidence_audit")
